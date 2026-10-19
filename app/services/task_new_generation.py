"""Explicit independent execution; reserved/accepted operations never requeue."""
import os
from typing import Literal
from uuid import UUID
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.config import settings
from app.models.note import LocalFileRequest
from app.models.source_request import SourceInput, SourceSubmission
from app.services.source_request_service import SourceRequestService
from app.services.task_artifact_service import TaskArtifactService
from app.services.task_generation_context import _frozen_generation_context, _read_json, _unavailable
from app.services.task_model_source import SNAPSHOT_FILE, validate_source
from app.services.task_original_service import TaskOriginalService
from app.services.retained_task_source import SOURCE_LOCK
from app.services.vilab_cloud_service import VILabCloudService


class NewGenerationConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_id: UUID
    confirmed: Literal[True]
    context_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    source_version: str = Field(pattern=r'^[0-9a-f]{64}$')
    canonical_task_id: UUID | None = None

    @field_validator('confirmed', mode='before')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('必须明确确认一次新的独立处理')
        return value


def _submission(parent, confirmation):
    if confirmation.canonical_task_id is not None:
        from app.services.parent_asr_prefix import prefix_submission
        return prefix_submission(_intent(parent, confirmation))
    return SourceSubmission(source=SourceInput(kind='retained_file',
        retained_file_id='task:' + parent, retained_file_version=confirmation.source_version),
        options={'contract': 'independent-frozen-generation-v1',
                 'parent_task_id': parent, 'context_revision': confirmation.context_revision})


def _intent(parent, confirmation, *, parent_prefix=None):
    link = {'version': 1, 'operation_id': str(confirmation.operation_id), 'parent_task_id': parent,
            'context_revision': confirmation.context_revision, 'source_version': confirmation.source_version}
    if confirmation.canonical_task_id is not None:
        link.update(version=2, canonical_task_id=str(confirmation.canonical_task_id))
        if parent_prefix is not None:
            link['parent_prefix'] = parent_prefix
    return link


class NewGenerationService:
    def __init__(self, receipts=None):
        self.receipts = receipts or SourceRequestService()
        self.artifacts = TaskArtifactService(settings.output_dir)

    def preflight_parent(self, owner, parent, normalized_wav):
        """Offline internal check; neither reserves an operation nor queues work."""
        from app.services.parent_asr_prefix import preflight_parent_prefix
        return preflight_parent_prefix(self.receipts, self.artifacts, owner=owner,
            parent_task_id=parent, normalized_wav=normalized_wav)

    def accept(self, owner, parent, confirmation, background, dispatch, *, active=False):
        operation = str(confirmation.operation_id)
        submission = _submission(parent, confirmation)
        # An existing operation is an immutable response, even if the original
        # source/model settings changed since acceptance. No worker resumption.
        try:
            self.receipts.get(owner, operation)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        else:
            return self.receipts.reserve(owner, operation, submission)
        with SOURCE_LOCK:
            context, parent_prefix = _frozen_generation_context(owner, parent, active=active, receipts=self.receipts)
            if (context['context_revision'] != confirmation.context_revision
                    or context['source']['version'] != confirmation.source_version
                    or context.get('canonical_task_id') != (
                        str(confirmation.canonical_task_id) if confirmation.canonical_task_id else None)):
                _unavailable('frozen_context_changed', '原文件或冻结设置已变化，请重新核验并确认。')
            folder = self.artifacts.find_task_dir(parent)
            canonical = context.get('canonical_task_id', parent)
            _, source = TaskOriginalService().get(owner, 'task:' + canonical)
            snapshot = validate_source(_read_json(folder / SNAPSHOT_FILE), owner)
            saved_request = _read_json(folder / 'request.json')
            request = saved_request['request']
            if request.get('workflow') != context['workflow']:
                _unavailable('workflow_changed', '原任务用途尚不能核验。')
            if self.artifacts._sha256(source) != confirmation.source_version:
                _unavailable('source_changed', '原文件版本已变化，未开始新的处理。')
            # No current preference capture or model substitution.
            cloud = VILabCloudService()
            with cloud.task_snapshot(owner, snapshot=snapshot):
                cloud.validate_ready(owner, needs_stt=True)
            claim = self.receipts.reserve(owner, operation, submission)
            if not claim.created:
                return claim
            child = self.artifacts.create_task_dir(claim.task_id)
            try:
                self.artifacts.write_text(child / 'recording_owner', owner)
                self.artifacts.write_text(child / '.task_id', claim.task_id)
                self.artifacts.write_json(child / 'source_reference.json', {
                    'version': 1, 'owner': owner, 'parent_task_id': canonical,
                    'source_version': confirmation.source_version})
                # The speaker service rechecks source/model signature and exact
                # duration; retaining this hint never authorizes ASR execution.
                speaker = folder / 'speaker_evidence.json'
                if speaker.is_file() and not speaker.is_symlink():
                    try:
                        cached_speaker = _read_json(speaker)
                    except HTTPException:
                        cached_speaker = None
                    if cached_speaker is not None:
                        self.artifacts.write_json(child / 'speaker_evidence.json', cached_speaker)
                self.artifacts.write_json(child / SNAPSHOT_FILE, snapshot)
                self.artifacts.write_json(child / 'source_media.json', _read_json(
                    self.artifacts.find_task_dir(canonical) / 'source_media.json'))
                # Only documented generation fields survive. Path and temporary
                # credentials/profile overrides cannot supersede the snapshot.
                options = {key: request[key] for key in (
                    'title', 'style', 'summary_mode', 'extras', 'output_language',
                    'diarize', 'speaker_count', 'workflow') if key in request}
                req = LocalFileRequest(file_path=str(source), **options)
                self.artifacts.write_json(child / 'request.json', {
                    'request': req.model_dump(exclude={'api_key', 'base_url', 'model_name'}), 'trace': saved_request.get('trace')})
                self.artifacts.write_json(child / 'new_generation.json', _intent(
                    parent, confirmation, parent_prefix=parent_prefix))
                origin = folder / 'generation_client'
                if origin.is_file() and not origin.is_symlink():
                    from app.services.note_origin_service import record_origin
                    record_origin(child, origin.read_text(encoding='utf-8'))
                # Recheck after durable reference installation; deletion between
                # preflight and staging cannot lead to a provider dispatch.
                if self.artifacts.resolve_source_media(child) != source or self.artifacts._sha256(source) != confirmation.source_version:
                    _unavailable('source_changed', '原文件已变化，未开始新的处理。')
                self.artifacts.update_status(child, 'preparing', '已确认原模型，正在准备新的处理。', retryable=False)
                receipt = self.receipts.accept(owner, operation, claim.task_id,
                    status='preparing', source_type=context['source']['type'])
                background.add_task(self.run_once, claim.task_id, owner, dispatch)
                return receipt
            except Exception:
                self.artifacts.update_status(child, 'failed', '新处理未能安全开始，请核验本次提交记录。', retryable=False)
                raise  # Reserved/accepted receipt remains queryable; never requeue.

    def run_once(self, task, owner, dispatch):
        folder = self.artifacts.find_task_dir(task)
        if not folder:
            return
        # Persistent exclusive claim precedes any provider interaction. Crash
        # after claim is an unknown execution, never automatically restarted.
        try:
            with (folder / 'new_generation_started').open('x', encoding='utf-8') as marker:
                marker.write('claimed')
                marker.flush()
                os.fsync(marker.fileno())
            if os.name != 'nt':
                directory = os.open(folder, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except FileExistsError:
            return
        try:
            if (folder / 'recording_owner').is_symlink() or (folder / 'recording_owner').read_text(encoding='utf-8') != owner:
                raise HTTPException(403, '无法核验任务归属')
            snapshot = validate_source(_read_json(folder / SNAPSHOT_FILE), owner)
            link = _read_json(folder / 'new_generation.json')
            reference = _read_json(folder / 'source_reference.json')
            if (link.get('canonical_task_id', link['parent_task_id']) != reference['parent_task_id']
                    or link['source_version'] != reference['source_version']):
                raise HTTPException(409, '原件引用不一致')
            source = self.artifacts.resolve_source_media(folder)
            if not source or self.artifacts._sha256(source) != reference['source_version']:
                raise HTTPException(409, '原文件不可用或已变化')
            cloud = VILabCloudService()
            from app.services.asr_execution_binding import _claimed_execution
            with cloud.task_snapshot(owner, snapshot=snapshot), _claimed_execution(
                    self.receipts, self.artifacts, owner, task, folder, snapshot, link, source):
                cloud.validate_ready(owner, needs_stt=True)
                req = LocalFileRequest(**{**_read_json(folder / 'request.json')['request'], 'file_path': str(source)})
                trace = _read_json(folder / 'request.json').get('trace')
                if trace:
                    from app.services.tracing_service import DesktopTraceContext
                    dispatch(task, req, owner, DesktopTraceContext(**trace))
                else:
                    dispatch(task, req, owner)
        except Exception as error:
            # No exception repr, credentials, content or paths in product errors.
            from app.transcribers.vilab_transcriber import _CheckpointEvidenceUnavailable
            message = ('原转写记录尚不能安全核验，原文件与记录已保留，未提交音频。'
                       if isinstance(error, _CheckpointEvidenceUnavailable) else
                       '本次处理未能通过原文件与模型核验，请查看处理记录。')
            self.artifacts.update_status(folder, 'failed', message, retryable=False)
