"""Confirmed summary-only children. No ASR, media copies or operation replay."""
import hashlib
import json
import math
import os
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, field_validator

from app.config import settings
from app.db_models import SourceRequestDB
from app.models.source_request import SourceInput, SourceSubmission
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.meeting_evidence import original_asr_evidence
from app.services.retained_task_source import SOURCE_LOCK, resolve_reference
from app.services.source_request_service import SourceRequestService, _fingerprint
from app.services.task_artifact_service import TaskArtifactService
from app.services.task_generation_context import _read_json, _unavailable
from app.services.task_model_source import SNAPSHOT_FILE, validate_source
from app.services.task_new_generation import NewGenerationConfirmation
from app.services.task_original_service import TaskOriginalService
from app.services.vilab_cloud_service import VILabCloudService
from app.llm.meeting_presentation import ContentDepth, Presentation, presentation_availability
from app.services.summary_visual_evidence import retained_visual_evidence, visual_version


class SummaryConfirmation(NewGenerationConfirmation):
    canonical_task_id: None = None  # v2 ASR donor selection is not summary input.
    model_name: str = Field(min_length=1, max_length=200)
    content_depth: ContentDepth | None = None
    presentation: Presentation | None = None
    connection_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator('model_name')
    @classmethod
    def explicit_model(cls, value):
        if value != value.strip():
            raise ValueError('请明确选择目录中的总结模型')
        return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


class SummaryPreflightError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _preflight(condition, code):
    if not condition:
        raise SummaryPreflightError(code)


def _submission(parent, body):
    return SourceSubmission(source=SourceInput(kind='retained_file',
        retained_file_id='task:' + parent, retained_file_version=body.source_version),
        options={'contract': 'meeting-summary-only-v1', 'parent_task_id': parent,
                 'context_revision': body.context_revision, 'model_name': body.model_name,
                 **{key: getattr(body, key) for key in ('content_depth', 'presentation', 'connection_id')
                    if getattr(body, key) is not None}})


def _snapshot(owner, model):
    connection = VILabCloudService().connection_snapshot(owner)
    return validate_source({'version': 1, 'owner': owner,
        **{key: value for key, value in connection.items()
           if key in {'mode', 'server_url', 'connection_id', 'connection_auth_mode', 'asr_model', 'llm_model'}},
        'llm_model': model, 'needs_stt': False}, owner)


def _options(saved, body=None):
    return {**{key: saved['request'][key] for key in ('title', 'extras', 'output_language')
               if key in saved['request']}, 'workflow': 'meeting', 'style': 'meeting',
            'summary_mode': 'default',
            **({'content_depth': body.content_depth or 'detailed',
                'presentation': body.presentation or 'text'}
               if body and (body.content_depth is not None or body.presentation is not None) else {})}


def _evidence(folder):
    """Only final persisted pipeline artifacts, never streaming/chunk caches.

    Saving these filenames is the existing whole-transcription commit contract;
    segment end times do not prove coverage, and gaps are retained verbatim.
    """
    material = {}
    for name in ('transcript.json', 'asr_evidence.json', 'speaker_evidence.json'):
        path = folder / name
        if not path.exists() and not path.is_symlink():
            continue
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
                raise ValueError()
            material[name] = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            _unavailable('summary_evidence_unavailable', '已保存的完整转写暂不能核验。')

    def parse(raw):
        if not isinstance(raw, dict):
            raise ValueError()
        metadata = raw.get('metadata', {})
        if not isinstance(metadata, dict):
            raise ValueError()
        for flags in (raw, metadata):
            if (flags.get('partial') or flags.get('incomplete') or flags.get('inflight')
                    or flags.get('complete') is False or flags.get('is_final') is False):
                raise ValueError()
        if not isinstance(raw.get('full_text'), str) or not raw['full_text'].strip():
            raise ValueError()
        segments = [TranscriptSegment(**segment) for segment in raw['segments']]
        if not segments or any(not isinstance(s.text, str) or not s.text.strip()
                or not math.isfinite(s.start) or not math.isfinite(s.end)
                or not 0 <= s.start < s.end for s in segments):
            raise ValueError()
        if metadata.get('asr_evidence') is not None:
            if ''.join(parse(metadata['asr_evidence']).full_text.split()) != ''.join(raw['full_text'].split()):
                raise ValueError()
        return TranscriptResult(raw.get('language'), raw['full_text'], segments, dict(metadata))

    try:
        saved = material.get('transcript.json', material.get('asr_evidence.json'))
        # Validate bounded nesting before parse's per-layer completeness checks.
        original = original_asr_evidence(saved)
        transcript = parse(saved)
        raw_asr = material.get('asr_evidence.json')
        if raw_asr is not None:
            file_original = original_asr_evidence(raw_asr)
            if ''.join(parse(raw_asr).full_text.split()) != ''.join(transcript.full_text.split()):
                raise ValueError()
            # A historical file may itself be an estimated transcript wrapper.
            # Prefer the original already embedded in the selected transcript.
            if transcript.metadata.get('asr_evidence') is None:
                original = file_original
        speaker = material.get('speaker_evidence.json')
        if original is not saved or raw_asr is not None or speaker is not None:
            # Keep the leaf's raw windows, granularity and explicit estimated
            # flags verbatim. Speaker overlap never supplies a sentence identity.
            transcript.metadata['asr_evidence'] = original
        if speaker is not None:
            turns = speaker['turns']
            if (speaker.get('timeline') != 'recording_offset_seconds' or not isinstance(turns, list)
                    or any(not math.isfinite(t['start']) or not math.isfinite(t['end'])
                           or not 0 <= t['start'] < t['end'] <= speaker['duration']
                           or not isinstance(t['speaker_id'], str) for t in turns)):
                raise ValueError()
            transcript.metadata['speaker_evidence'] = turns
        return transcript, _digest(material)
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        _unavailable('summary_evidence_unavailable', '缺少可核验的完整转写，请保留原文件和处理记录。')


class SummaryRegenerationService:
    def __init__(self, receipts=None):
        self.receipts = receipts or SourceRequestService()
        self.artifacts = TaskArtifactService(settings.output_dir)

    def _context(self, owner, parent, *, active=False):
        try:
            if str(UUID(parent)) != parent:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(404, 'Task not found') from None
        folder = self.artifacts.find_task_dir(parent)
        if (not folder or folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)()
                or folder.resolve().parent != self.artifacts.output_dir.resolve()):
            raise HTTPException(404, 'Task not found')
        try:
            marker = folder / 'recording_owner'
            mapping = folder / '.task_id'
            if (marker.is_symlink() or marker.read_text(encoding='utf-8') != owner
                    or mapping.is_symlink() or (folder / 'recording_deleted').exists()
                    or (mapping.read_text(encoding='utf-8').strip() if mapping.exists() else folder.name) != parent):
                raise ValueError()
        except (OSError, ValueError):
            raise HTTPException(404, 'Task not found')
        reference = None
        canonical = parent
        path = folder / 'source_reference.json'
        if path.exists() or path.is_symlink():
            # Existing resolver verifies one owner-bound canonical hop, no chains.
            if resolve_reference(self.artifacts, folder) is None:
                raise HTTPException(404, 'Task not found')
            reference = _read_json(path)
            canonical = reference['parent_task_id']
        info, source = TaskOriginalService().get(owner, 'task:' + canonical)
        if info['task_id'] != canonical:
            raise HTTPException(404, 'Task not found')
        if active or _read_json(folder / 'status.json').get('status') not in {'failed', 'error', 'success'}:
            _unavailable('task_active', '原任务尚未结束，请先查询原任务状态。')
        saved = _read_json(folder / 'request.json')
        if saved['request'].get('workflow') != 'meeting':
            _unavailable('summary_workflow_unavailable', '本操作仅支持已保留完整转写的会议。')
        snapshot = validate_source(_read_json(folder / SNAPSHOT_FILE), owner)
        manifest = _read_json(self.artifacts.find_task_dir(canonical) / 'source_media.json')
        version = self.artifacts._sha256(source)
        if manifest.get('sha256') != version or reference and reference['source_version'] != version:
            _unavailable('source_changed', '原文件版本已变化，未开始重新总结。')
        transcript, transcript_version = _evidence(folder)
        visual = retained_visual_evidence(self.artifacts, folder, canonical, source, owner)
        context = {'protocol': 1, 'parent_task_id': parent, 'canonical_task_id': canonical, 'workflow': 'meeting',
            'source': {'file_id': info['id'], 'title': info['title'], 'type': info['source_type'], 'version': version},
            'transcript_version': transcript_version, 'requires_confirmation': True,
            'can_regenerate_summary': True}
        context['presentation_options'] = presentation_availability(has_visuals=visual is not None)
        context['visual_evidence_version'] = visual_version(visual)
        context['context_revision'] = _digest({'owner': owner, 'context': context,
            'request': saved, 'snapshot': snapshot, 'source_reference': reference})
        return context, folder, source, transcript, saved

    def context(self, owner, parent, *, active=False):
        with SOURCE_LOCK:
            return self._context(owner, parent, active=active)[0]

    def accept(self, owner, parent, body, background, note_service=None, *, active=False):
        operation = str(body.operation_id)
        submission = _submission(parent, body)
        try:
            self.receipts.get(owner, operation)
        except HTTPException as error:
            if error.status_code != 404:
                raise
        else:
            return self.receipts.reserve(owner, operation, submission)  # Query only, even if reserved.
        with SOURCE_LOCK:
            context, folder, source, transcript, saved = self._context(owner, parent, active=active)
            if (context['context_revision'] != body.context_revision
                    or context['source']['version'] != body.source_version):
                _unavailable('summary_context_changed', '原文件或转写已变化，请重新核验并确认。')
            option = context['presentation_options'][body.presentation or 'text']
            if not option['available']:
                _unavailable('summary_presentation_unavailable', option['reason'])
            cloud = VILabCloudService()
            if cloud.status(owner)['mode'] != 'cloud':
                _unavailable('summary_cloud_required', '请明确选择云端总结模型后再确认。')
            snapshot = _snapshot(owner, body.model_name)
            if body.connection_id is not None and body.connection_id != snapshot.get('connection_id'):
                _unavailable('summary_connection_changed', '模型连接已变化，请重新核验并确认。')
            with cloud.task_snapshot(owner, snapshot=snapshot):
                cloud.validate_ready(owner, needs_stt=False)
            claim = self.receipts.reserve(owner, operation, submission)
            if not claim.created:
                return claim
            child = self.artifacts.create_task_dir(claim.task_id)
            try:
                self.artifacts.write_text(child / 'recording_owner', owner)
                self.artifacts.write_text(child / '.task_id', claim.task_id)
                # Install the query-only guard before exposing a retryable request.
                self.artifacts.write_json(child / 'new_generation.json', {
                    'contract': 'meeting-summary-only-v1', 'parent_task_id': parent,
                    **body.model_dump(mode='json')})
                self.artifacts.write_json(child / 'source_reference.json', {'version': 1, 'owner': owner,
                    'parent_task_id': context['canonical_task_id'], 'source_version': body.source_version})
                self.artifacts.write_json(child / SNAPSHOT_FILE, snapshot)
                self.artifacts.write_json(child / 'request.json', {'request': _options(saved, body)})
                self.artifacts.write_json(child / 'summary_presentation.json', {
                    'protocol': 1, 'content_depth': body.content_depth or 'detailed',
                    'presentation': body.presentation or 'text', 'operation_id': operation,
                    'task_id': claim.task_id, 'parent_task_id': parent,
                    'canonical_task_id': context['canonical_task_id'], 'model_name': body.model_name,
                    'source_version': body.source_version, 'transcript_version': context['transcript_version'],
                    'visual_evidence_version': context['visual_evidence_version']})
                self.artifacts.save_transcript(child, transcript)
                self.artifacts.write_text(child / 'generation_client', 'desktop')
                if self.artifacts.resolve_source_media(child) != source or self.artifacts._sha256(source) != body.source_version:
                    _unavailable('source_changed', '原文件已变化，未开始重新总结。')
                self.artifacts.update_status(child, 'preparing', '已确认重新总结，正在准备已保存的转写。', retryable=False)
                receipt = self.receipts.accept(owner, operation, claim.task_id,
                    status='preparing', source_type=context['source']['type'])
                # Server-owned accepted receipt binds every frozen source field.
                # Disk JSON and the mutable global selection cannot self-authorize.
                with self.receipts.sessions() as db:
                    row = db.get(SourceRequestDB, (owner, operation))
                    _preflight(row is not None and row.state == 'accepted' and row.task_id == claim.task_id
                        and row.fingerprint == _fingerprint(submission), 'summary_preflight_snapshot_changed')
                    bound = json.loads(row.receipt_json or '{}')
                    bound['summary_snapshot_sha256'] = _digest(snapshot)
                    row.receipt_json = json.dumps(bound)
                    db.flush()
                background.add_task(self.run_once, claim.task_id, owner, note_service)
                return receipt
            except Exception:
                self.artifacts.update_status(child, 'failed', '本次提交尚不能安全执行，请查询原回执。', retryable=False)
                raise

    def run_once(self, task, owner, note_service=None):
        try:
            valid = str(UUID(task)) == task
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            return
        folder = self.artifacts.find_task_dir(task)
        if not folder or folder.is_symlink() or folder.resolve().parent != self.artifacts.output_dir.resolve():
            return
        preparing = True
        try:
            link = _read_json(folder / 'new_generation.json')
            body = SummaryConfirmation(**{key: link[key] for key in SummaryConfirmation.model_fields if key in link})
            if link.get('contract') != 'meeting-summary-only-v1':
                raise ValueError()
            with self.receipts.sessions() as db:
                row = db.get(SourceRequestDB, (owner, str(body.operation_id)))
                if (not row or row.state != 'accepted' or row.task_id != task
                        or row.fingerprint != _fingerprint(_submission(link['parent_task_id'], body))):
                    raise ValueError()  # Disk artifacts and arbitrary IDs never authorize execution.
                accepted_snapshot_sha256 = json.loads(row.receipt_json or '{}').get('summary_snapshot_sha256')
                _preflight(isinstance(accepted_snapshot_sha256, str) and len(accepted_snapshot_sha256) == 64,
                    'summary_preflight_snapshot_changed')
            try:
                with (folder / 'summary_generation_started').open('x', encoding='utf-8') as marker:
                    marker.write('claimed')
                    marker.flush()
                    os.fsync(marker.fileno())
                if os.name != 'nt':
                    descriptor = os.open(folder, os.O_RDONLY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            except FileExistsError:
                return
            with SOURCE_LOCK:
                context, parent_folder, source, transcript, saved = self._context(owner, link['parent_task_id'])
                snapshot = validate_source(_read_json(folder / SNAPSHOT_FILE), owner)
                _preflight(not (folder / 'recording_owner').is_symlink()
                    and (folder / 'recording_owner').read_text(encoding='utf-8') == owner, 'summary_preflight_owner_changed')
                _preflight(not (folder / '.task_id').is_symlink()
                    and (folder / '.task_id').read_text(encoding='utf-8') == task, 'summary_preflight_task_changed')
                _preflight(context['context_revision'] == body.context_revision, 'summary_preflight_context_changed')
                _preflight(context['source']['version'] == body.source_version
                    and self.artifacts.resolve_source_media(folder) == source, 'summary_preflight_source_changed')
                _preflight(_read_json(folder / 'source_reference.json') == {'version': 1, 'owner': owner,
                    'parent_task_id': context['canonical_task_id'], 'source_version': body.source_version}, 'summary_preflight_reference_changed')
                _preflight(_read_json(folder / 'request.json') == {'request': _options(saved, body)}, 'summary_preflight_request_changed')
                _preflight(_digest(snapshot) == accepted_snapshot_sha256
                    and snapshot['mode'] == 'cloud' and snapshot.get('needs_stt') is False
                    and snapshot['llm_model'] == body.model_name
                    and (body.connection_id is None or body.connection_id == snapshot.get('connection_id')),
                    'summary_preflight_snapshot_changed')
                visual = retained_visual_evidence(self.artifacts, parent_folder,
                    context['canonical_task_id'], source, owner)
                _preflight(visual_version(visual) == context['visual_evidence_version'], 'summary_preflight_visual_changed')
            if note_service is None:
                from app.services.note_service import NoteService
                note_service = NoteService()
            with VILabCloudService().task_snapshot(owner, snapshot=snapshot):
                preparing = False
                note_service.generate_from_transcript(transcript=transcript, task_id=task, user_id=owner,
                    **({'video_evidence': visual} if visual is not None else {}),
                    **{key: value for key, value in _options(saved, body).items() if key != 'workflow'})
        except Exception as error:
            try:
                status = _read_json(folder / 'status.json')
            except HTTPException:
                status = {}
            if status.get('status') in {'failed', 'error'}:
                # Keep the pipeline's specific failure/stage; never replace it
                # with an ASR/unknown label or copy exception text into status.
                if status.get('retryable') is not False:
                    self.artifacts.write_json(folder / 'status.json', {**status, 'retryable': False})
                return
            self.artifacts.update_status(folder, 'failed', '本次总结结果尚未确认，请查询原任务，未自动重试。',
                retryable=False, failed_stage=status.get('stage') or ('preparing' if preparing else 'summarizing'),
                **({'error_code': error.code if isinstance(error, SummaryPreflightError) else
                    'summary_preflight_visual_unavailable' if isinstance(error, HTTPException)
                        and isinstance(error.detail, dict) and error.detail.get('code') == 'summary_visual_evidence_unavailable'
                    else 'summary_preflight_unconfirmed'} if preparing else {}))
