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


class SummaryConfirmation(NewGenerationConfirmation):
    canonical_task_id: None = None  # v2 ASR donor selection is not summary input.
    model_name: str = Field(min_length=1, max_length=200)

    @field_validator('model_name')
    @classmethod
    def explicit_model(cls, value):
        if value != value.strip():
            raise ValueError('请明确选择目录中的总结模型')
        return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _submission(parent, body):
    return SourceSubmission(source=SourceInput(kind='retained_file',
        retained_file_id='task:' + parent, retained_file_version=body.source_version),
        options={'contract': 'meeting-summary-only-v1', 'parent_task_id': parent,
                 'context_revision': body.context_revision, 'model_name': body.model_name})


def _snapshot(owner, model):
    return validate_source({'version': 1, 'owner': owner, 'mode': 'cloud',
        'server_url': settings.vilab_server_url, 'asr_model': '',
        'llm_model': model, 'needs_stt': False}, owner)


def _options(saved):
    return {**{key: saved['request'][key] for key in ('title', 'extras', 'output_language')
               if key in saved['request']}, 'workflow': 'meeting', 'style': 'meeting',
            'summary_mode': 'default'}


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
        context = {'protocol': 1, 'parent_task_id': parent, 'canonical_task_id': canonical, 'workflow': 'meeting',
            'source': {'file_id': info['id'], 'title': info['title'], 'type': info['source_type'], 'version': version},
            'transcript_version': transcript_version, 'requires_confirmation': True,
            'can_regenerate_summary': True}
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
            cloud = VILabCloudService()
            if cloud.status(owner)['mode'] != 'cloud':
                _unavailable('summary_cloud_required', '请明确选择云端总结模型后再确认。')
            snapshot = _snapshot(owner, body.model_name)
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
                self.artifacts.write_json(child / 'request.json', {'request': _options(saved)})
                self.artifacts.save_transcript(child, transcript)
                self.artifacts.write_text(child / 'generation_client', 'desktop')
                if self.artifacts.resolve_source_media(child) != source or self.artifacts._sha256(source) != body.source_version:
                    _unavailable('source_changed', '原文件已变化，未开始重新总结。')
                self.artifacts.update_status(child, 'preparing', '已确认重新总结，正在准备已保存的转写。', retryable=False)
                receipt = self.receipts.accept(owner, operation, claim.task_id,
                    status='preparing', source_type=context['source']['type'])
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
        try:
            link = _read_json(folder / 'new_generation.json')
            body = SummaryConfirmation(**{key: link[key] for key in SummaryConfirmation.model_fields})
            if link.get('contract') != 'meeting-summary-only-v1':
                raise ValueError()
            with self.receipts.sessions() as db:
                row = db.get(SourceRequestDB, (owner, str(body.operation_id)))
                if (not row or row.state != 'accepted' or row.task_id != task
                        or row.fingerprint != _fingerprint(_submission(link['parent_task_id'], body))):
                    raise ValueError()  # Disk artifacts and arbitrary IDs never authorize execution.
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
                context, _, source, transcript, saved = self._context(owner, link['parent_task_id'])
                snapshot = validate_source(_read_json(folder / SNAPSHOT_FILE), owner)
                if ((folder / 'recording_owner').is_symlink()
                        or (folder / 'recording_owner').read_text(encoding='utf-8') != owner
                        or (folder / '.task_id').is_symlink()
                        or (folder / '.task_id').read_text(encoding='utf-8') != task
                        or context['context_revision'] != body.context_revision
                        or context['source']['version'] != body.source_version
                        or self.artifacts.resolve_source_media(folder) != source
                        or _read_json(folder / 'source_reference.json') != {'version': 1, 'owner': owner,
                            'parent_task_id': context['canonical_task_id'], 'source_version': body.source_version}
                        or _read_json(folder / 'request.json') != {'request': _options(saved)}
                        or snapshot != _snapshot(owner, body.model_name)):
                    raise ValueError()
            if note_service is None:
                from app.services.note_service import NoteService
                note_service = NoteService()
            with VILabCloudService().task_snapshot(owner, snapshot=snapshot):
                note_service.generate_from_transcript(transcript=transcript, task_id=task, user_id=owner,
                    **{key: value for key, value in _options(saved).items() if key != 'workflow'})
        except Exception:
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
                                         retryable=False, failed_stage=status.get('stage') or 'summarizing')
