"""Explicit new ASR execution, never a donor-prefix recovery or replay."""
import hashlib
import json
import os
import time
from contextlib import ExitStack
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings
from app.db_models import SourceRequestDB
from app.models.note import LocalFileRequest
from app.models.source_request import SourceInput, SourceSubmission
from app.services.retained_task_source import SOURCE_LOCK, resolve_reference
from app.services.source_request_service import SourceRequestService, _fingerprint
from app.services.task_artifact_service import TaskArtifactService
from app.services.task_generation_context import _read_json, _unavailable
from app.services.task_model_source import SNAPSHOT_FILE, validate_source
from app.services.task_original_service import TaskOriginalService
from app.services.vilab_cloud_service import VILabCloudService, _task_source

CONTRACT = 'meeting-fresh-asr-v1'


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class FreshASRConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_id: UUID
    confirmed: bool
    asr_mode: str
    llm_mode: str
    extra_asr_consent: bool
    context_revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    fresh_context_revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    selection_revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_version: str = Field(pattern=r'^[a-f0-9]{64}$')
    asr_model: str = Field(min_length=1, max_length=200)
    model_name: str = Field(min_length=1, max_length=200)
    connection_id: str | None = Field(default=None, min_length=1, max_length=200)
    content_depth: str = 'concise'
    presentation: str = 'text'

    @field_validator('confirmed', 'extra_asr_consent', mode='before')
    @classmethod
    def consent(cls, value):
        if value is not True:
            raise ValueError('请明确确认重新识别录音，这会产生新的 ASR 处理')
        return value

    @field_validator('asr_mode', 'llm_mode', 'asr_model', 'model_name', 'content_depth', 'presentation')
    @classmethod
    def choices(cls, value, info):
        choices = {'asr_mode': {'fresh'}, 'llm_mode': {'select'},
                   'content_depth': {'brief', 'concise', 'detailed'},
                   'presentation': {'text', 'illustrated', 'html', 'comic', 'infographic'}}
        if value != value.strip() or info.field_name in choices and value not in choices[info.field_name]:
            raise ValueError('请明确选择本次重新识别的设置')
        return value


def _body(value):
    return FreshASRConfirmation.model_validate({key: getattr(value, key)
        for key in FreshASRConfirmation.model_fields if hasattr(value, key)})


def _submission(link):
    """Public-to-adapter fingerprint helper; JSON alone is never execution authority."""
    body = FreshASRConfirmation.model_validate({key: link[key]
        for key in FreshASRConfirmation.model_fields if key in link})
    if (link.get('contract') != CONTRACT or str(UUID(link['parent_task_id'])) != link['parent_task_id']
            or str(UUID(link['canonical_task_id'])) != link['canonical_task_id']):
        raise ValueError('Invalid fresh contract')
    expected = {'contract', 'parent_task_id', 'canonical_task_id', 'snapshot_sha256', *body.model_dump().keys()}
    if set(link) != expected or not isinstance(link['snapshot_sha256'], str) or len(link['snapshot_sha256']) != 64:
        raise ValueError('Invalid fresh intent')
    return SourceSubmission(source=SourceInput(kind='retained_file',
        retained_file_id='task:' + link['canonical_task_id'], retained_file_version=body.source_version),
        options={key: value for key, value in link.items() if key != 'operation_id'})


def _accepted(receipts, owner, task, link, snapshot):
    bound_snapshot = None
    if link.get('contract') == CONTRACT:
        submission = _submission(link)
        if link['snapshot_sha256'] != _digest(snapshot):
            raise ValueError('Changed fresh snapshot')
    elif link.get('contract') == 'meeting-summary-only-v1':
        from app.services.meeting_summary_regeneration import SummaryConfirmation, _submission as summary_submission
        body = SummaryConfirmation(**{key: link[key] for key in SummaryConfirmation.model_fields if key in link})
        submission = summary_submission(link['parent_task_id'], body)
    else:
        from app.services.parent_asr_prefix import _submission as independent_submission
        submission = independent_submission(link)
    with receipts.sessions() as db:
        row = db.get(SourceRequestDB, (owner, link['operation_id']))
        if (not row or row.state != 'accepted' or row.task_id != task
                or row.fingerprint != _fingerprint(submission)):
            raise ValueError('Unbound accepted operation')
        if link.get('contract') == 'meeting-summary-only-v1':
            bound_snapshot = json.loads(row.receipt_json or '{}').get('summary_snapshot_sha256')
    if link.get('contract') == 'meeting-summary-only-v1':
        if (snapshot.get('needs_stt') is not False or snapshot.get('llm_model') != body.model_name
                or body.connection_id is not None and snapshot.get('connection_id') != body.connection_id):
            raise ValueError('Unbound summary models')
        if bound_snapshot is None:
            # Reuse the adapter's exact historical hash proof only AFTER the
            # accepted owner/task/fingerprint gate. Never rewrite a receipt or
            # fall back from a present-but-mismatched modern snapshot digest.
            from app.services.meeting_summary_regeneration import SummaryRegenerationService
            from app.services.meeting_version_context import MeetingVersionService
            proof = MeetingVersionService(summary=SummaryRegenerationService(receipts))
            if not proof._legacy_origin_proof(owner, link, snapshot):
                raise ValueError('Unbound historical summary origin')
            return True
        if bound_snapshot != _digest(snapshot):
            raise ValueError('Unbound summary snapshot')
    return False


def _context(receipts, artifacts, owner, parent, *, active=False):
    from app.services.parent_asr_prefix import _safe
    try:
        if str(UUID(parent)) != parent:
            raise ValueError()
        folder = _safe(artifacts.find_task_dir(parent), artifacts.output_dir.absolute())
        if folder.parent != artifacts.output_dir.absolute():
            raise ValueError()
        marker = _safe(folder / 'recording_owner', artifacts.output_dir.absolute())
        mapping = _safe(folder / '.task_id', artifacts.output_dir.absolute())
        if (marker.read_text(encoding='utf-8') != owner or (folder / 'recording_deleted').exists()
                or (mapping.read_text(encoding='utf-8').strip() if mapping.exists() else folder.name) != parent):
            raise ValueError()
        status = _read_json(folder / 'status.json').get('status')
        if active or status not in {'success', 'failed', 'error'}:
            _unavailable('task_active', '原任务尚未结束，请先查看处理记录。')
        saved = _read_json(folder / 'request.json')
        snapshot = validate_source(_read_json(folder / SNAPSHOT_FILE), owner)
        if saved.get('request', {}).get('workflow') != 'meeting':
            raise ValueError()
        canonical, reference, link = parent, None, None
        if (folder / 'source_reference.json').exists() or (folder / 'source_reference.json').is_symlink():
            reference = _read_json(folder / 'source_reference.json')
            if resolve_reference(artifacts, folder) is None:
                raise ValueError()
            canonical = reference['parent_task_id']
            link = _read_json(folder / 'new_generation.json')
            name = 'summary_generation_started' if link.get('contract') == 'meeting-summary-only-v1' else 'new_generation_started'
            if _safe(folder / name, artifacts.output_dir.absolute()).read_text(encoding='utf-8') != 'claimed':
                raise ValueError()
            legacy_origin = _accepted(receipts, owner, parent, link, snapshot)
            if (link['source_version'] != reference['source_version']
                    or link.get('canonical_task_id', link['parent_task_id']) != canonical):
                # Summary children may name a selected parent while referencing
                # the canonical source. Their accepted receipt + resolver bind it.
                if link.get('contract') != 'meeting-summary-only-v1' or link['source_version'] != reference['source_version']:
                    raise ValueError()
            if link.get('contract') == 'meeting-summary-only-v1':
                from app.services.meeting_summary_regeneration import SummaryRegenerationService
                prior = SummaryRegenerationService(receipts)._context(owner, link['parent_task_id'])[0]
                if ((not legacy_origin and prior['context_revision'] != link['context_revision'])
                        or prior['canonical_task_id'] != canonical):
                    raise ValueError('Summary original reference changed')
        original = _safe(artifacts.find_task_dir(canonical), artifacts.output_dir.absolute())
        info, source = TaskOriginalService().get(owner, 'task:' + canonical)
        original_snapshot = validate_source(_read_json(original / SNAPSHOT_FILE), owner)
        original_request = _read_json(original / 'request.json')
        # A summary-only snapshot can retain an ASR ID for display; it is never
        # proof that this original was an ASR media task.
        if (original_snapshot.get('needs_stt') is not True or original_snapshot.get('mode') != 'cloud'
                or not original_snapshot.get('asr_model') or info['category'] not in {'recording', 'video'}
                or info['purpose'] != 'meeting' or original_request.get('request', {}).get('workflow') != 'meeting'
                or (original / 'new_generation.json').exists()
                or _read_json(original / 'status.json').get('status') not in {'success', 'failed', 'error'}):
            raise ValueError()
        if link is not None and not link.get('contract') and snapshot != original_snapshot:
            raise ValueError('Independent inherited ASR snapshot changed')
        version = artifacts._sha256(source)
        media = _read_json(original / 'source_media.json')
        if (media.get('sha256') != version
                or reference is not None and reference['source_version'] != version):
            raise ValueError()
        public = {'available': True, 'parent_task_id': parent, 'canonical_task_id': canonical,
            'source': {'file_id': info['id'], 'title': info['title'], 'type': info['source_type'], 'version': version},
            'frozen_models': {key: original_snapshot[key] for key in
                ('server_url', 'asr_model', 'llm_model', 'connection_id', 'connection_auth_mode') if key in original_snapshot}}
        from app.llm.meeting_presentation import presentation_availability
        public['presentation_options'] = presentation_availability(has_visuals=media.get('media_kind') == 'video')
        public['context_revision'] = _digest({'owner': owner, 'context': public, 'status': status,
            'request': saved, 'snapshot': snapshot, 'reference': reference, 'link': link,
            'original_request': original_request, 'original_snapshot': original_snapshot})
        return public, folder, source, saved
    except (ValueError, TypeError, AttributeError, OSError, KeyError):
        _unavailable('fresh_asr_source_unverified', '原录音与转写来源暂不能核验，未开始重新识别。')


def _pristine(folder):
    if any((folder / name).exists() or (folder / name).is_symlink() for name in
           ('transcript.json', 'asr_evidence.json', 'speaker_evidence.json', 'transcription_chunks')):
        raise ValueError('Fresh execution cannot adopt a preexisting cache')


def _validate_claim(receipts, artifacts, owner, task, folder, snapshot, link, source):
    marker = folder / 'new_generation_started'
    if marker.is_symlink() or marker.read_text(encoding='utf-8') != 'claimed':
        raise ValueError('Missing exclusive fresh execution claim')
    _accepted(receipts, owner, task, link, snapshot)
    context, _, actual, _ = _context(receipts, artifacts, owner, link['parent_task_id'])
    if (context['context_revision'] != link['fresh_context_revision']
            or context['source']['version'] != link['source_version']
            or context['canonical_task_id'] != link['canonical_task_id'] or actual != source
            or snapshot.get('needs_stt') is not True or snapshot.get('mode') != 'cloud'
            or snapshot['asr_model'] != link['asr_model'] or snapshot['llm_model'] != link['model_name']):
        raise ValueError('Fresh source or selected models changed')
    _pristine(folder)


class FreshASRService:
    def __init__(self, receipts=None):
        self.receipts = receipts or SourceRequestService()
        self.artifacts = TaskArtifactService(settings.output_dir)

    def context(self, owner, parent, *, active=False):
        with SOURCE_LOCK:
            return _context(self.receipts, self.artifacts, owner, parent, active=active)[0]

    def accept(self, owner, parent, body, background, note_service=None, *, active=False):
        body = _body(body)
        operation = str(body.operation_id)
        try:
            previous = self.receipts.get(owner, operation)
        except HTTPException as error:
            if error.status_code != 404:
                raise
        else:
            # Duplicate/unknown is a receipt lookup, never a worker resumption.
            folder = self.artifacts.find_task_dir(previous.task_id)
            link = _read_json(folder / 'new_generation.json') if folder else {}
            if link.get('parent_task_id') != parent or any(link.get(key) != value for key, value in body.model_dump(mode='json').items()):
                _unavailable('fresh_operation_reused', '该操作已绑定其他设置，请查询原提交记录。')
            return self.receipts.reserve(owner, operation, _submission(link))
        with SOURCE_LOCK:
            context, folder, source, saved = _context(self.receipts, self.artifacts, owner, parent, active=active)
            if context['context_revision'] != body.fresh_context_revision or context['source']['version'] != body.source_version:
                _unavailable('fresh_context_changed', '原文件或处理记录已变化，请重新核验并确认。')
            option = context['presentation_options'][body.presentation]
            if not option['available']:
                _unavailable('fresh_presentation_unavailable', option['reason'])
            cloud = VILabCloudService()
            frozen = _task_source.get()
            connection = dict(frozen[1]) if frozen and frozen[0] == owner else cloud.connection_snapshot(owner)
            if connection.get('mode') != 'cloud' or body.connection_id is not None and body.connection_id != connection.get('connection_id'):
                _unavailable('fresh_connection_changed', '模型连接已变化，请重新选择并确认。')
            snapshot = validate_source({'version': 1, 'owner': owner, **{key: connection[key] for key in
                ('mode', 'server_url', 'connection_id', 'connection_auth_mode') if key in connection},
                'asr_model': body.asr_model, 'llm_model': body.model_name, 'needs_stt': True}, owner)
            with cloud.task_snapshot(owner, snapshot=snapshot):
                models = cloud.models(owner)
                cloud._validate_selection(models, body.asr_model, 'asr')
                cloud._validate_selection(models, body.model_name, 'llm')
                cloud.validate_ready(owner, needs_stt=True)
            link = {'contract': CONTRACT, 'parent_task_id': parent, 'canonical_task_id': context['canonical_task_id'],
                    'snapshot_sha256': _digest(snapshot), **body.model_dump(mode='json')}
            claim = self.receipts.reserve(owner, operation, _submission(link))
            if not claim.created:
                return claim
            child = self.artifacts.create_task_dir(claim.task_id)
            try:
                self.artifacts.write_text(child / 'recording_owner', owner)
                self.artifacts.write_text(child / '.task_id', claim.task_id)
                self.artifacts.write_json(child / 'new_generation.json', link)
                self.artifacts.write_json(child / 'source_reference.json', {'version': 1, 'owner': owner,
                    'parent_task_id': context['canonical_task_id'], 'source_version': body.source_version})
                self.artifacts.write_json(child / SNAPSHOT_FILE, snapshot)
                self.artifacts.write_json(child / 'source_media.json', _read_json(
                    self.artifacts.find_task_dir(context['canonical_task_id']) / 'source_media.json'))
                options = {key: saved['request'][key] for key in
                    ('title', 'extras', 'output_language', 'diarize', 'speaker_count') if key in saved['request']}
                req = LocalFileRequest(file_path=str(source), workflow='meeting', style='meeting', summary_mode='default', **options)
                self.artifacts.write_json(child / 'request.json', {'request': req.model_dump(
                    exclude={'api_key', 'base_url', 'model_name', 'asr_model'}),
                    'content_depth': body.content_depth, 'presentation': body.presentation})
                self.artifacts.write_text(child / 'generation_client', 'desktop')
                _pristine(child)
                if self.artifacts.resolve_source_media(child) != source or self.artifacts._sha256(source) != body.source_version:
                    raise ValueError('Source changed')
                self.artifacts.update_status(child, 'preparing', '已确认重新识别，正在准备原录音。', retryable=False)
                receipt = self.receipts.accept(owner, operation, claim.task_id, status='preparing', source_type=context['source']['type'])
                background.add_task(self.run_once, claim.task_id, owner, note_service)
                return receipt
            except Exception:
                self.artifacts.update_status(child, 'failed', '本次提交尚不能安全执行，请查询原回执。', retryable=False)
                raise

    def run_once(self, task, owner, note_service=None):
        try:
            if str(UUID(task)) != task:
                return
        except (ValueError, TypeError, AttributeError):
            return
        folder = self.artifacts.find_task_dir(task)
        if not folder or folder.is_symlink() or folder.resolve().parent != self.artifacts.output_dir.resolve():
            return
        try:
            with (folder / 'new_generation_started').open('x', encoding='utf-8') as marker:
                marker.write('claimed'); marker.flush(); os.fsync(marker.fileno())
            if os.name != 'nt':
                descriptor = os.open(folder, os.O_RDONLY)
                try: os.fsync(descriptor)
                finally: os.close(descriptor)
        except FileExistsError:
            return
        try:
            with ExitStack() as execution:
                with SOURCE_LOCK:
                    snapshot = validate_source(_read_json(folder / SNAPSHOT_FILE), owner)
                    link = _read_json(folder / 'new_generation.json')
                    source = self.artifacts.resolve_source_media(folder)
                    from app.services.asr_execution_binding import _claimed_execution
                    execution.enter_context(VILabCloudService().task_snapshot(owner, snapshot=snapshot))
                    execution.enter_context(_claimed_execution(
                        self.receipts, self.artifacts, owner, task, folder, snapshot, link, source))
                    req = LocalFileRequest(**_read_json(folder / 'request.json')['request'])
                    if req.file_path != str(source):
                        raise ValueError('Changed source request')
                # Do not hold the source registry lock through paid execution.
                VILabCloudService().validate_ready(owner, needs_stt=True)
                if note_service is None:
                    from app.services.note_service import NoteService
                    note_service = NoteService()
                _dispatch(note_service, self.artifacts, folder, source, owner, task, req, link)
        except Exception:
            # Keep lower-layer typed failures and unknown markers verbatim.
            previous = self.artifacts.get_status(task)
            if previous.get('status') not in {'failed', 'error'}:
                self.artifacts.update_status(folder, 'failed', '重新识别未能安全完成，请查询本次处理记录。', retryable=False)


def _dispatch(service, artifacts, folder, source, owner, task, req, link):
    """Prepare existing media pipeline without changing its frozen host methods.

    generate_from_file predates presentation/depth arguments. Use its same
    preparation + pipeline here so explicit choices reach the actual context.
    The caller keeps both the fresh ASR lease and model snapshot live throughout.
    """
    started = time.time()
    if req.diarize:
        from app.services.speaker_diarization_service import SpeakerDiarizationService
        SpeakerDiarizationService.require_ready()
    from app.services.asr_execution_binding import require_task_execution
    require_task_execution(owner, task, folder, source)
    artifacts.update_status(folder, 'preparing', '正在准备本次重新识别的录音…', retryable=False)
    audio_meta = service._build_local_audio_meta(file_path=str(source), task_id=task, title=req.title)
    if audio_meta.file_path != str(source):
        raise ValueError('Fresh preparation changed the retained source')
    artifacts.save_audio_meta(folder, audio_meta)
    return service._run_pipeline(task_id=task, task_dir=folder, audio_meta=audio_meta,
        style='meeting', summary_mode='default', extras=req.extras, output_language=req.output_language,
        model_profile_id=None, stt_profile_id=None, model_name=None, api_key=None, base_url=None,
        user_id=owner, source_video_url=None, diarize=req.diarize, speaker_count=req.speaker_count,
        task_start_time=started, preloaded_transcript=None, step_timings={'prepare': time.time() - started},
        content_depth=link['content_depth'], presentation=link['presentation'])
