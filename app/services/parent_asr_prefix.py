"""Read-only direct-parent seed for a newly confirmed independent operation.

This helper does not grant an execution lease, queue work, save a checkpoint or
call a provider. The caller still needs the winning run_once live lease. Hold
this context (and the existing global identity lock) through remaining sends.
Never fall back to a shorter global prefix if this selected donor fails.
"""
from contextlib import ExitStack, contextmanager
import hashlib
import json
from pathlib import Path
import re
import wave
from uuid import UUID

from fastapi import HTTPException

from app.db_models import SourceRequestDB
from app.models.source_request import SourceInput, SourceSubmission
from app.services.asr_checkpoint_lock import checkpoint_lock
from app.services.source_request_service import _fingerprint
from app.services.task_generation_context import _read_json
from app.services.task_model_source import SNAPSHOT_FILE, validate_source
from app.transcribers.vilab_transcriber import _CheckpointEvidenceUnavailable, _read_donor

_LINK_KEYS = {'version', 'operation_id', 'parent_task_id', 'context_revision', 'source_version'}


def _link(value, *, prefix=False):
    version = 2 if prefix else 1
    keys = _LINK_KEYS | ({'canonical_task_id'} if prefix else set())
    if not isinstance(value, dict) or set(value) != keys or type(value['version']) is not int or value['version'] != version:
        raise ValueError('Invalid independent intent')
    for key in ('operation_id', 'parent_task_id', *(['canonical_task_id'] if prefix else [])):
        if str(UUID(value[key])) != value[key]:
            raise ValueError('Invalid identity')
    for key in ('context_revision', 'source_version'):
        if not isinstance(value[key], str) or not re.fullmatch('[0-9a-f]{64}', value[key]):
            raise ValueError('Invalid version')
    if prefix and value['parent_task_id'] == value['canonical_task_id']:
        raise ValueError('Expected an independent direct parent')
    return value


def prefix_submission(link):
    """Use for reserve/duplicate checks AND live-lease fingerprint validation.

    link is the exact persisted version=2 new_generation.json: operation_id,
    parent_task_id (direct independent parent), canonical_task_id (one-hop
    original), context_revision, source_version. No path/donor hint is accepted.
    """
    # The opaque revision cryptographically commits the server-read prefix.
    # Keep duplicate reserved/accepted POSTs checkable from client intent alone,
    # even if the parent later disappears; disk prefix metadata is not authority.
    if 'parent_prefix' in link:
        validate_prefix_snapshot(link['parent_prefix'])
    link = _link({k: v for k, v in link.items() if k != 'parent_prefix'}, prefix=True)
    return SourceSubmission(source=SourceInput(kind='retained_file',
        retained_file_id='task:' + link['canonical_task_id'],
        retained_file_version=link['source_version']), options={
            'contract': 'independent-parent-prefix-v1',
            **{key: link[key] for key in ('parent_task_id', 'canonical_task_id', 'context_revision')}})


def validate_prefix_snapshot(value):
    if (not isinstance(value, dict) or set(value) != {'checkpoint_sha256', 'confirmed_end_frame'}
            or not isinstance(value['checkpoint_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', value['checkpoint_sha256'])
            or type(value['confirmed_end_frame']) is not int
            or not 0 < value['confirmed_end_frame'] < 2 ** 53):
        raise ValueError('Invalid frozen parent prefix')
    return dict(value)


def _submission(link):
    if link.get('version') == 2:
        return prefix_submission(link)
    _link(link)
    # Match existing v1 operations exactly, never migrate/rewrite their receipt.
    return SourceSubmission(source=SourceInput(kind='retained_file',
        retained_file_id='task:' + link['parent_task_id'],
        retained_file_version=link['source_version']), options={
            'contract': 'independent-frozen-generation-v1',
            'parent_task_id': link['parent_task_id'], 'context_revision': link['context_revision']})


def _safe(path, root):
    path = Path(path).absolute()
    if not path.is_relative_to(root) or path.resolve() != path:
        raise ValueError('Uncontained evidence')
    for component in (path, *path.parents):
        if component.is_symlink() or getattr(component, 'is_junction', lambda: False)():
            raise ValueError('Linked evidence')
        if component == root:
            break
    return path


def _task(artifacts, owner, task_id):
    if str(UUID(task_id)) != task_id:
        raise ValueError('Invalid task')
    root = artifacts.output_dir.absolute()
    folder = _safe(artifacts.find_task_dir(task_id), root)
    if folder.parent != root:
        raise ValueError('Invalid task folder')
    for name, expected in (('recording_owner', owner), ('.task_id', task_id),
                           ('new_generation_started', 'claimed')):
        if _safe(folder / name, root).read_text(encoding='utf-8') != expected:
            raise ValueError('Unbound task')
    for name in ('new_generation.json', SNAPSHOT_FILE, 'source_reference.json', 'status.json'):
        _safe(folder / name, root)
    return folder


def _accepted(receipts, owner, task, link):
    expected = _fingerprint(_submission(link))
    with receipts.sessions() as db:
        row = db.get(SourceRequestDB, (owner, link['operation_id']))
        if not row or row.state != 'accepted' or row.task_id != task or row.fingerprint != expected:
            raise ValueError('Unbound durable operation')


def selected_parent_original(receipts, artifacts, owner, parent_task_id):
    """Offline context: accepted failed independent parent, one canonical source."""
    parent = _task(artifacts, owner, parent_task_id)
    if _read_json(parent / 'status.json').get('status') not in {'failed', 'error'}:
        raise ValueError('Parent is not a terminal failure')
    link = _read_json(parent / 'new_generation.json')
    _accepted(receipts, owner, parent_task_id, link)
    canonical = link.get('canonical_task_id', link['parent_task_id'])
    reference = {'version': 1, 'owner': owner, 'parent_task_id': canonical,
                 'source_version': link['source_version']}
    if _read_json(parent / 'source_reference.json') != reference or canonical == parent_task_id:
        raise ValueError('Invalid canonical binding')
    from app.services.retained_task_source import resolve_reference
    from app.services.task_original_service import TaskOriginalService
    info, source = TaskOriginalService().get(owner, 'task:' + canonical)
    if resolve_reference(artifacts, parent) != source:
        raise ValueError('Invalid canonical source')
    return info, source, canonical, link


@contextmanager
def _locked_selected_prefix(receipts, artifacts, *, owner, parent_task_id, canonical_task_id,
                            source_version, snapshot, normalized_identity, total_frames):
    """Yield only {completed, seed}; caller adds its OWN execution stamp/fsync.

    A parent's nonoverlapping inflight tail is deliberately excluded, never
    resumed under its old operation. A missing/invalid/busy chosen parent is
    an error, including when the global cache could supply a shorter prefix.
    The parent process lock remains held until this context exits. Parent v1
    and v2 stamps are verified against their own accepted DB operation, without
    traversing their execution ancestry. Source references remain one-hop.
    """
    with ExitStack() as locks:
        try:
            context_only = normalized_identity is None and total_frames is None
            if not context_only and (type(total_frames) is not int or total_frames <= 0
                    or not isinstance(normalized_identity, str)
                    or not re.fullmatch('[0-9a-f]{64}', normalized_identity)):
                raise ValueError('Invalid normalized audio identity')
            link = {'source_version': source_version}
            parent_id, canonical = parent_task_id, canonical_task_id
            if parent_id == canonical:
                raise ValueError('Cyclic operation')
            parent = _task(artifacts, owner, parent_id)
            donor = _safe(parent / 'transcription_chunks' / 'vilab_stream', artifacts.output_dir.absolute())
            if not donor.is_dir():
                raise ValueError('Missing parent checkpoint')
            _safe(donor / 'recognition.process.lock', artifacts.output_dir.absolute())
            locks.enter_context(checkpoint_lock(donor))
            # Recheck parent binding/status after obtaining its execution lock.
            _task(artifacts, owner, parent_id)
            if _read_json(parent / 'status.json').get('status') not in {'failed', 'error'}:
                raise ValueError('Parent is not a confirmed terminal failure')
            parent_link = _read_json(parent / 'new_generation.json')
            _accepted(receipts, owner, parent_id, parent_link)
            if (parent_link.get('canonical_task_id', parent_link['parent_task_id']) != canonical
                    or parent_link['source_version'] != link['source_version']):
                raise ValueError('Different canonical source')
            snapshot = validate_source(snapshot, owner)
            if (snapshot['mode'] != 'cloud' or snapshot.get('needs_stt') is False
                    or validate_source(_read_json(parent / SNAPSHOT_FILE), owner) != snapshot):
                raise ValueError('Different frozen models')
            reference = {'version': 1, 'owner': owner, 'parent_task_id': canonical,
                         'source_version': link['source_version']}
            if _read_json(parent / 'source_reference.json') != reference:
                raise ValueError('Noncanonical reference')
            from app.services.task_original_service import TaskOriginalService
            canonical_folder = artifacts.find_task_dir(canonical)
            _safe(canonical_folder, artifacts.output_dir.absolute())
            if _safe(canonical_folder / 'recording_owner', artifacts.output_dir.absolute()).read_text(encoding='utf-8') != owner:
                raise ValueError('Unbound original')
            mapping = _safe(canonical_folder / '.task_id', artifacts.output_dir.absolute())
            if (mapping.read_text(encoding='utf-8') if mapping.exists() else canonical_folder.name) != canonical:
                raise ValueError('Unbound original mapping')
            if ((canonical_folder / 'source_reference.json').exists()
                    or (canonical_folder / 'source_reference.json').is_symlink()):
                raise ValueError('Source reference chain')
            _, source = TaskOriginalService().get(owner, 'task:' + canonical)
            if (_read_json(canonical_folder / 'source_media.json').get('sha256') != link['source_version']
                    or artifacts._sha256(source) != link['source_version']):
                raise ValueError('Changed source bytes')
            record = _safe(donor / 'recognition.json', artifacts.output_dir.absolute())
            if record.stat().st_size > 16 * 1024 * 1024:
                raise ValueError('Oversized parent checkpoint')
            with record.open('rb') as stream:
                raw = stream.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError('Oversized parent checkpoint')
            saved = json.loads(raw)
            if context_only:
                # Context reads do not normalize media or trust an old plan's
                # duration. Validate integer-sample prefix structure now; the
                # execution separately bounds it against its actual WAV frames.
                normalized_identity = saved.get('execution', {}).get('normalized_identity')
                if not isinstance(normalized_identity, str) or not re.fullmatch('[0-9a-f]{64}', normalized_identity):
                    raise ValueError('Missing normalized identity')
                total_frames = 2 ** 53 - 1
            stamp = {'version': 1, 'owner': owner, 'task_id': parent_id,
                **{key: parent_link[key] for key in ('operation_id', 'parent_task_id', 'source_version', 'context_revision')},
                'snapshot_sha256': hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest(),
                'normalized_identity': normalized_identity}
            if json.dumps(saved.get('execution'), sort_keys=True) != json.dumps(stamp, sort_keys=True):
                raise ValueError('Unbound parent execution')
            parts, digest = _read_donor(donor, total_frames)
            if not parts or digest != hashlib.sha256(raw).hexdigest():
                raise ValueError('Missing or changed confirmed prefix')
            seed = {'completed': parts, 'seed': {'version': 2, 'donor_task_id': parent_id,
                'donor_identity': normalized_identity, 'checkpoint_sha256': digest,
                'confirmed_end_frame': round(parts[-1]['end'] * 16000)}}
        except (HTTPException, OSError, ValueError, TypeError, KeyError, OverflowError, AttributeError):
            raise _CheckpointEvidenceUnavailable() from None
        yield seed


@contextmanager
def locked_parent_prefix(receipts, artifacts, *, owner, task_id, normalized_identity, total_frames,
                         expected_prefix=None):
    """Validate the new accepted intent; caller must also hold its live lease."""
    with ExitStack() as locks:
        try:
            child = _task(artifacts, owner, task_id)
            link = _read_json(child / 'new_generation.json')
            _link({k: v for k, v in link.items() if k != 'parent_prefix'}, prefix=True)
            frozen = validate_prefix_snapshot(link.get('parent_prefix'))
            if expected_prefix is not None and frozen != validate_prefix_snapshot(expected_prefix):
                raise ValueError('Different live-lease prefix')
            _accepted(receipts, owner, task_id, link)
            if task_id in (link['parent_task_id'], link['canonical_task_id']):
                raise ValueError('Cyclic operation')
            reference = {'version': 1, 'owner': owner, 'parent_task_id': link['canonical_task_id'],
                         'source_version': link['source_version']}
            if _read_json(child / 'source_reference.json') != reference:
                raise ValueError('Invalid child source')
            seed = locks.enter_context(_locked_selected_prefix(receipts, artifacts, owner=owner,
                parent_task_id=link['parent_task_id'], canonical_task_id=link['canonical_task_id'],
                source_version=link['source_version'], snapshot=_read_json(child / SNAPSHOT_FILE),
                normalized_identity=normalized_identity, total_frames=total_frames))
            actual = {key: seed['seed'][key] for key in ('checkpoint_sha256', 'confirmed_end_frame')}
            if actual != frozen:
                raise ValueError('Parent checkpoint changed since confirmation')
        except (HTTPException, OSError, ValueError, TypeError, KeyError, AttributeError):
            raise _CheckpointEvidenceUnavailable() from None
        yield seed


def parent_prefix_snapshot(receipts, artifacts, *, owner, parent_task_id):
    """Strict snapshot under the parent OS lock, without media or provider calls."""
    _, _, canonical, link = selected_parent_original(receipts, artifacts, owner, parent_task_id)
    snapshot = _read_json(artifacts.find_task_dir(parent_task_id) / SNAPSHOT_FILE)
    with _locked_selected_prefix(receipts, artifacts, owner=owner, parent_task_id=parent_task_id,
            canonical_task_id=canonical, source_version=link['source_version'], snapshot=snapshot,
            normalized_identity=None, total_frames=None) as seed:
        return validate_prefix_snapshot({key: seed['seed'][key]
            for key in ('checkpoint_sha256', 'confirmed_end_frame')})


def preflight_parent_prefix(receipts, artifacts, *, owner, parent_task_id, normalized_wav):
    """Internal offline check using the EXACT pipeline-normalized WAV; no claim.

    No client path API is exposed. The caller supplies a privately prepared WAV
    from the same preprocessing/FFmpeg path. It must match the stored identity;
    raw media, alternate normalization and merely matching duration fail closed.
    """
    from app.services.task_generation_context import _frozen_generation_context
    context, frozen = _frozen_generation_context(owner, parent_task_id, receipts=receipts)
    if context['protocol'] != 2:
        raise _CheckpointEvidenceUnavailable()
    snapshot = _read_json(artifacts.find_task_dir(parent_task_id) / SNAPSHOT_FILE)
    path = Path(normalized_wav)
    if path.is_symlink():
        raise _CheckpointEvidenceUnavailable()
    with wave.open(str(path), 'rb') as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth(), source.getcomptype()) != (16000, 1, 2, 'NONE'):
            raise _CheckpointEvidenceUnavailable()
        frames = source.getnframes()
    digest = hashlib.sha256(json.dumps([snapshot['server_url'].rstrip('/'), owner,
                                       snapshot['asr_model']], ensure_ascii=False).encode())
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    with _locked_selected_prefix(receipts, artifacts, owner=owner, parent_task_id=parent_task_id,
            canonical_task_id=context['canonical_task_id'], source_version=context['source']['version'],
            snapshot=snapshot, normalized_identity=digest.hexdigest(), total_frames=frames) as seed:
        if {key: seed['seed'][key] for key in ('checkpoint_sha256', 'confirmed_end_frame')} != frozen:
            raise _CheckpointEvidenceUnavailable()
        end = seed['seed']['confirmed_end_frame']
        return {'parent_task_id': parent_task_id, 'canonical_task_id': context['canonical_task_id'],
            'context_revision': context['context_revision'], 'source_version': context['source']['version'],
            'normalized_identity': digest.hexdigest(), 'confirmed_parts': len(seed['completed']),
            'typed_empty_parts': sum(p.get('recognition_outcome') == 'provider_terminal_empty' for p in seed['completed']),
            'confirmed_end_frame': end, 'total_frames': frames, 'remaining_frames': frames - end,
            'checkpoint_sha256': seed['seed']['checkpoint_sha256']}
