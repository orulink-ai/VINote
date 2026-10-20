"""Read existing source-bound visual material without scanning or modifying donors."""
from pathlib import Path
import json
from uuid import UUID
from contextvars import ContextVar
from contextlib import contextmanager
from fastapi import HTTPException

from app.services.video_evidence_service import VideoEvidenceService
from app.services.task_generation_context import _unavailable, _read_json

REFERENCE_FILE = 'summary_visual_reference.json'
_legacy_readers = ContextVar('summary_legacy_visual_readers', default=())
_legacy_selected_cache = ContextVar('summary_legacy_selected_visual_cache', default=None)


@contextmanager
def legacy_selected_visual_cache(task):
    """Read only this exact parent's OWN cache while rebuilding a legacy hash."""
    token = _legacy_selected_cache.set(task)
    try:
        yield
    finally:
        _legacy_selected_cache.reset(token)


def _legacy_owned_origin(artifacts, folder, canonical, owner, version, receipts, link, snapshot, bound):
    """Only the existing pre-presentation proof can admit an old OWN cache."""
    expected = {'contract', 'parent_task_id', 'operation_id', 'confirmed', 'canonical_task_id',
                'context_revision', 'source_version', 'model_name'}
    if (set(link) != expected or link['canonical_task_id'] is not None or link['confirmed'] is not True
            or 'summary_snapshot_sha256' in bound or 'summary_visual_reference_sha256' in bound
            or (folder / REFERENCE_FILE).exists() or (folder / REFERENCE_FILE).is_symlink()
            or not (folder / 'video_evidence.json').is_file()
            or snapshot.get('needs_stt') is not False or snapshot.get('llm_model') != link['model_name']):
        return False
    task = (folder / '.task_id').read_text(encoding='utf-8').strip()
    seen = _legacy_readers.get()
    if task in seen or len(seen) >= 8:
        return False
    token = _legacy_readers.set((*seen, task))
    try:
        _claimed(folder)
        _load(artifacts, folder, canonical, artifacts.resolve_source_media(folder), owner, version)
        from app.services.meeting_summary_regeneration import SummaryRegenerationService
        from app.services.meeting_version_context import MeetingVersionService
        from app.services.task_model_source import validate_source
        snapshot = validate_source(snapshot, owner)
        service = SummaryRegenerationService(receipts)
        service.artifacts = artifacts
        # Reconstruct the exact selected context using its own validated cache,
        # as the historical algorithm did. This is not authorization to borrow
        # through that parent's ancestry or a different visual reference.
        with legacy_selected_visual_cache(link['parent_task_id']):
            selected = service._context(owner, link['parent_task_id'])
        if (selected[0]['canonical_task_id'] != canonical or selected[0]['source']['version'] != version):
            return False
        # Reuse the exact existing legacy algorithm with the current, already
        # validated selected context. No lookup of old final prose or rescanning.
        from types import SimpleNamespace
        proof = MeetingVersionService(summary=SimpleNamespace(_context=lambda *a, **k: selected))
        return proof._legacy_origin_proof(owner, link, snapshot)
    finally:
        _legacy_readers.reset(token)


def _owned(artifacts, task, owner, canonical, version):
    if str(UUID(task)) != task:
        raise ValueError('Invalid visual donor')
    folder = artifacts.find_task_dir(task)
    if (folder is None or folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)()
            or folder.resolve().parent != artifacts.output_dir.resolve()):
        raise ValueError('Invalid visual donor')
    for name, expected in [('recording_owner', owner), ('.task_id', task)]:
        path = folder / name
        value = path.read_text(encoding='utf-8') if not path.is_symlink() else None
        if (value.strip() if value is not None and name == '.task_id' else value) != expected:
            raise ValueError('Changed visual donor owner or mapping')
    if (folder / 'recording_deleted').exists():
        raise ValueError('Deleted visual donor')
    reference = folder / 'source_reference.json'
    if task != canonical:
        if _read_json(reference) != {'version': 1, 'owner': owner,
                'parent_task_id': canonical, 'source_version': version}:
            raise ValueError('Changed canonical visual source')
    elif reference.exists() or reference.is_symlink():
        raise ValueError('Canonical reference chain')
    return folder


def _load(artifacts, folder, canonical, source, owner, version):
    """Load a concrete manifest only, never follow a donor's reference."""
    task = (folder / '.task_id').read_text(encoding='utf-8').strip()
    _owned(artifacts, task, owner, canonical, version)
    service = VideoEvidenceService()
    manifest = folder / 'video_evidence.json'
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Invalid visual manifest')
    before = artifacts._sha256(manifest)
    evidence = service._load(folder, service._identity(source, folder.resolve(), owner))
    if evidence is None or artifacts._sha256(folder / 'video_evidence.json') != before:
        raise ValueError('Changed visual manifest')
    evidence._manifest_path = evidence._manifest_payload = None
    from app.services.video_evidence_service import _frame_digest
    evidence._summary_frame_hashes = {frame.image_path: _frame_digest(frame.image_path) for frame in evidence.frames}
    evidence._summary_visual_donor_task_id = task
    evidence._summary_visual_manifest_sha256 = before
    return evidence


def visual_reference(evidence, *, owner, task, canonical, source_version):
    """A flattened, source-bound pointer; contains neither paths nor images."""
    if evidence is None:
        return None
    return {'protocol': 1, 'owner': owner, 'task_id': task,
        'canonical_task_id': canonical, 'source_version': source_version,
        'donor_task_id': evidence._summary_visual_donor_task_id,
        'manifest_sha256': evidence._summary_visual_manifest_sha256,
        'visual_evidence_version': visual_version(evidence)}


def _accepted_summary(artifacts, folder, canonical, owner, version, receipts, *, allow_absent=False):
    """Disk links alone never authorize an external visual donor."""
    from app.db_models import SourceRequestDB
    from app.services.meeting_summary_regeneration import SummaryConfirmation, _submission, _digest
    from app.services.source_request_service import SourceRequestService, _fingerprint
    from app.services.task_model_source import SNAPSHOT_FILE
    link = _read_json(folder / 'new_generation.json')
    if link.get('contract') != 'meeting-summary-only-v1':
        raise ValueError('Not a summary receipt')
    task = (folder / '.task_id').read_text(encoding='utf-8').strip()
    _owned(artifacts, task, owner, canonical, version)
    body = SummaryConfirmation(**{key: link[key] for key in SummaryConfirmation.model_fields if key in link})
    if body.source_version != version:
        raise ValueError('Changed visual source')
    receipts = receipts or SourceRequestService()
    with receipts.sessions() as db:
        row = db.get(SourceRequestDB, (owner, str(body.operation_id)))
        if (row is None or row.state != 'accepted' or row.task_id != task
                or row.fingerprint != _fingerprint(_submission(link['parent_task_id'], body))):
            raise ValueError('Unbound visual origin')
        bound = json.loads(row.receipt_json or '{}')
    if allow_absent and bound.get('summary_visual_reference_sha256') is None:
        # No visual material is not a visual borrowing operation. In particular,
        # do not turn audio-only model-inheritance checks into visual failures.
        # A bound (even missing-on-disk) pointer never enters this branch.
        candidates = [folder, artifacts.find_task_dir(canonical),
                      artifacts.find_task_dir(link['parent_task_id'])]
        if all(candidate is None or all(not (candidate / name).exists()
                and not (candidate / name).is_symlink() for name in ('video_evidence.json', REFERENCE_FILE))
                for candidate in candidates):
            return link, body, bound, receipts
    snapshot_hash = bound.get('summary_snapshot_sha256')
    snapshot = _read_json(folder / SNAPSHOT_FILE)
    if (not isinstance(snapshot_hash, str) or len(snapshot_hash) != 64
            or snapshot_hash != _digest(snapshot)):
        if not _legacy_owned_origin(artifacts, folder, canonical, owner, version,
                receipts, link, snapshot, bound):
            raise ValueError('Changed visual origin snapshot')
    return link, body, bound, receipts


def _claimed(folder):
    stamp = folder / 'summary_generation_started'
    if stamp.is_symlink() or stamp.read_text(encoding='utf-8') != 'claimed':
        raise ValueError('Unclaimed visual origin')


def retained_visual_evidence(artifacts, folder: Path, canonical: str, source: Path, owner: str, *, receipts=None):
    try:
        version = artifacts._sha256(source)
        path = folder / 'video_evidence.json'
        has_own = path.exists() or path.is_symlink()
        reference_path = folder / REFERENCE_FILE
        if (has_own and not reference_path.exists() and not reference_path.is_symlink()
                and _legacy_selected_cache.get() == (folder / '.task_id').read_text(encoding='utf-8').strip()):
            return _load(artifacts, folder, canonical, source, owner, version)
        link_path = folder / 'new_generation.json'
        summary = link_path.exists() and _read_json(link_path).get('contract') == 'meeting-summary-only-v1'
        if reference_path.exists() or reference_path.is_symlink() or summary:
            link, body, bound, receipts = _accepted_summary(
                artifacts, folder, canonical, owner, version, receipts,
                allow_absent=not has_own and not reference_path.exists() and not reference_path.is_symlink())
            expected = bound.get('summary_visual_reference_sha256')
            if reference_path.exists() or reference_path.is_symlink() or expected is not None:
                _claimed(folder)
                from app.services.meeting_summary_regeneration import _digest
                reference = _read_json(reference_path)
                if expected is None or _digest(reference) != expected:
                    raise ValueError('Unbound visual reference')
                donor = _owned(artifacts, reference['donor_task_id'], owner, canonical, version)
                evidence = _load(artifacts, donor, canonical, source, owner, version)
                if reference != visual_reference(evidence, owner=owner,
                        task=(folder / '.task_id').read_text(encoding='utf-8').strip(),
                        canonical=canonical, source_version=version):
                    raise ValueError('Changed visual reference')
                return evidence
            if has_own:
                return _load(artifacts, folder, canonical, source, owner, version)
            if 'summary_visual_reference_sha256' not in bound:
                # Historical children have no pointer. Only the DB-bound selected
                # parent and its exact accepted context can prove this donor.
                donor = _owned(artifacts, link['parent_task_id'], owner, canonical, version)
                if (donor / 'video_evidence.json').exists() or (donor / 'video_evidence.json').is_symlink():
                    _claimed(folder)
                    evidence = _load(artifacts, donor, canonical, source, owner, version)
                    from app.services.meeting_summary_regeneration import SummaryRegenerationService
                    service = SummaryRegenerationService(receipts)
                    service.artifacts = artifacts
                    context = service._context(owner, link['parent_task_id'])[0]
                    if (context['context_revision'] != body.context_revision
                            or context['canonical_task_id'] != canonical
                            or context['visual_evidence_version'] != visual_version(evidence)):
                        raise ValueError('Changed historical visual context')
                    return evidence
        elif has_own:
            return _load(artifacts, folder, canonical, source, owner, version)
        original = artifacts.find_task_dir(canonical)
        if original is not None:
            path = original / 'video_evidence.json'
            if path.exists() or path.is_symlink():
                return _load(artifacts, original, canonical, source, owner, version)
        return None
    except (OSError, ValueError, KeyError, TypeError, AttributeError, HTTPException):
        _unavailable('summary_visual_evidence_unavailable', '已保存的视频证据已变化或无法核验，未重新扫描。')


def visual_version(evidence):
    if evidence is None:
        return None
    from app.services.meeting_summary_regeneration import _digest
    from app.services.video_evidence_service import _frame_digest
    return _digest({'duration': evidence.duration, 'frames': [
        {'timestamp': frame.timestamp, 'offsets': frame.sample_offsets,
         'ocr': frame.ocr_text, 'ocr_status': frame.ocr_status,
         'sha256': _frame_digest(frame.image_path)} for frame in evidence.frames]})
