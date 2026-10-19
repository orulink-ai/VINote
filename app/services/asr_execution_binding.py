"""Internal, revocable execution lease. Disk metadata is never authorization.

Only NewGenerationService's winning run_once claim enters _claimed_execution.
The existing receipt getter and a read-only fingerprint lookup verify that claim;
no reserve(), public request field or database migration is involved.
"""
import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.db_models import SourceRequestDB
from app.services.source_request_service import _fingerprint
from app.services.task_generation_context import _read_json, _frozen_generation_context
from app.services.task_model_source import SNAPSHOT_FILE, validate_source

_execution = ContextVar('independent_asr_execution', default=None)


def _deny():
    raise ValueError('本次处理的原文件与模型信息尚不能核验，未提交音频')


@dataclass(frozen=True)
class ASRExecutionBinding:
    owner: str
    operation: str
    task: str
    parent: str
    source_version: str
    revision: str
    folder: Path
    source: Path
    snapshot_json: str
    canonical: str | None = None
    parent_prefix_json: str | None = None
    _receipts: object = field(default=None, compare=False, repr=False)
    # Revocation also invalidates copy_context snapshots retained after dispatch.
    _live: list = field(default_factory=lambda: [True], compare=False, repr=False)

    @property
    def chunks(self):
        return self.folder / 'transcription_chunks'

    def stamp(self):
        return {'version': 1, 'owner': self.owner, 'operation_id': self.operation,
                'task_id': self.task, 'parent_task_id': self.parent,
                'source_version': self.source_version, 'context_revision': self.revision,
                'snapshot_sha256': hashlib.sha256(self.snapshot_json.encode()).hexdigest()}

    def validate(self, *, owner=None, task=None, folder=None, source=None, chunks=None):
        from app.services.task_artifact_service import TaskArtifactService
        from app.services.vilab_cloud_service import _task_source
        if not self._live[0] or _execution.get() is not self:
            _deny()
        if ((owner is not None and owner != self.owner) or (task is not None and task != self.task)
                or (folder is not None and Path(folder).resolve() != self.folder)
                or (source is not None and Path(source).resolve() != self.source)
                or (chunks is not None and Path(chunks).resolve() != self.chunks)):
            _deny()
        if self.folder.is_symlink() or not self.folder.is_relative_to(Path(settings.output_dir).resolve()):
            _deny()
        if ((self.folder / '.task_id').is_symlink()
                or (self.folder / '.task_id').read_text(encoding='utf-8') != self.task
                or (self.folder / 'recording_owner').is_symlink()
                or (self.folder / 'recording_owner').read_text(encoding='utf-8') != self.owner):
            _deny()
        snapshot = validate_source(_read_json(self.folder / SNAPSHOT_FILE), self.owner)
        if json.dumps(snapshot, sort_keys=True) != self.snapshot_json:
            _deny()
        bound_owner, frozen = _task_source.get() or (None, {})
        if bound_owner != self.owner or any(frozen.get(k) != v for k, v in snapshot.items()):
            _deny()
        reference = _read_json(self.folder / 'source_reference.json')
        link = _read_json(self.folder / 'new_generation.json')
        expected_link = {'version': 1, 'operation_id': self.operation, 'parent_task_id': self.parent,
                         'source_version': self.source_version, 'context_revision': self.revision}
        if self.canonical is not None:
            if self.parent_prefix_json is None:
                _deny()
            expected_link.update(version=2, canonical_task_id=self.canonical,
                                 parent_prefix=json.loads(self.parent_prefix_json))
        if (reference != {'version': 1, 'owner': self.owner, 'parent_task_id': self.canonical or self.parent,
                          'source_version': self.source_version}
                or link != expected_link):
            _deny()
        artifacts = TaskArtifactService(settings.output_dir)
        if (artifacts.resolve_source_media(self.folder) != self.source
                or artifacts._sha256(self.source) != self.source_version):
            _deny()

    def validate_model(self, owner, origin, model):
        self.validate()
        snapshot = json.loads(self.snapshot_json)
        if (owner != self.owner or origin.rstrip('/') != snapshot['server_url'].rstrip('/')
                or model != snapshot['asr_model']):
            _deny()


def current_execution():
    binding = _execution.get()
    if binding is not None and not binding._live[0]:
        _deny()
    return binding


def require_task_execution(owner, task, folder, source):
    binding = current_execution()
    folder = Path(folder)
    if binding is None:
        if any((folder / name).exists() or (folder / name).is_symlink()
               for name in ('new_generation.json', 'source_reference.json', 'new_generation_started')):
            _deny()
        return None
    if owner != binding.owner or task != binding.task:
        _deny()
    binding.validate(owner=owner, task=task, folder=folder, source=source)
    return binding


@contextmanager
def _claimed_execution(receipts, artifacts, owner, task, folder, snapshot, link, source):
    """Called only after the exclusive persisted run_once claim, before dispatch."""
    from app.services.task_new_generation import NewGenerationConfirmation, _submission
    if folder.is_symlink():
        _deny()
    confirmation = NewGenerationConfirmation(confirmed=True, **{
        key: link[key] for key in ('operation_id', 'context_revision', 'source_version', 'canonical_task_id') if key in link})
    operation = str(confirmation.operation_id)
    receipt = receipts.get(owner, operation)  # Existing owner-scoped read API.
    expected = _fingerprint(_submission(link['parent_task_id'], confirmation))
    with receipts.sessions() as db:  # Private consistency check; read only.
        row = db.get(SourceRequestDB, (owner, operation))
        if (not row or row.state != 'accepted' or row.task_id != task
                or row.fingerprint != expected or receipt.state != 'accepted' or receipt.task_id != task):
            _deny()
    context, parent_prefix = _frozen_generation_context(owner, link['parent_task_id'], receipts=receipts)
    parent_folder = artifacts.find_task_dir(link['parent_task_id'])
    if (context['context_revision'] != link['context_revision']
            or context['source']['version'] != link['source_version']
            or context.get('canonical_task_id') != link.get('canonical_task_id')
            or (link.get('canonical_task_id') is not None and link.get('parent_prefix') != parent_prefix)
            or validate_source(_read_json(parent_folder / SNAPSHOT_FILE), owner) != snapshot
            or snapshot['mode'] != 'cloud'):
        _deny()
    binding = ASRExecutionBinding(owner, operation, task, link['parent_task_id'], link['source_version'],
                                  link['context_revision'], folder.resolve(), source.resolve(),
                                  json.dumps(snapshot, sort_keys=True), canonical=link.get('canonical_task_id'),
                                  parent_prefix_json=json.dumps(parent_prefix, sort_keys=True) if parent_prefix is not None else None,
                                  _receipts=receipts)
    token = _execution.set(binding)
    try:
        binding.validate(owner=owner, task=task, folder=folder, source=source)
        yield binding
    finally:
        binding._live[0] = False
        _execution.reset(token)
