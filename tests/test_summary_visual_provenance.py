"""Concrete source-bound visual donors; synthetic DB only, no ASR/network/OCR."""
import json
from uuid import uuid4
from unittest.mock import Mock

import pytest
from fastapi import BackgroundTasks, HTTPException
from PIL import Image

from tests.test_meeting_summary_regeneration import case, accept
from app.db_models import SourceRequestDB
from app.services.summary_visual_evidence import REFERENCE_FILE
from app.services.video_evidence_service import VideoEvidenceService, VideoEvidence, VideoFrameEvidence


@pytest.fixture
def provenance(case, monkeypatch):
    c = case
    monkeypatch.setattr('app.services.meeting_video_ocr.prepare_meeting_video_ocr', lambda evidence, **kw: evidence)
    monkeypatch.setattr(VideoEvidenceService, 'collect', Mock(side_effect=AssertionError('NEVER rescan')))
    donor_receipt, _ = accept(c)
    donor = c.artifacts.find_task_dir(donor_receipt.task_id)
    c.artifacts.update_status(donor, 'success', 'synthetic donor')
    images = donor / 'video_evidence'; images.mkdir()
    frame = images / 'frame.jpg'; Image.new('RGB', (10, 10)).save(frame)
    evidence = VideoEvidence(10, [VideoFrameEvidence(0, frame, ['timeline'], [0, 9], 'screen', 'recognized')], 10, True)
    video = VideoEvidenceService()
    video._save(donor, evidence, video._identity(c.original, donor.resolve(), 'alice'))
    # A stale historical canonical cache must neither win nor be rewritten.
    c.artifacts.write_json(c.folder / 'video_evidence.json', {'version': 'stale canonical'})
    context = c.service.context('alice', donor_receipt.task_id)
    body = c.body.model_copy(update={'operation_id': uuid4(), 'context_revision': context['context_revision']})
    receipt = c.service.accept('alice', donor_receipt.task_id, body, BackgroundTasks(), c.note)
    child = c.artifacts.find_task_dir(receipt.task_id)
    c.service.run_once(receipt.task_id, 'alice', c.note)
    assert c.note.generate_from_transcript.call_count == 1
    c.artifacts.update_status(child, 'success', 'synthetic saved HTML')
    return c, donor, frame, receipt, child


def test_saved_child_and_next_version_reuse_flattened_visual_pointer_without_copies(provenance):
    c, donor, frame, receipt, child = provenance
    before = {p: p.read_bytes() for folder in (donor, c.folder, child) for p in folder.rglob('*') if p.is_file()}
    context = c.service.context('alice', receipt.task_id)
    assert context['visual_evidence_version'] and context['canonical_task_id'] == c.parent
    link = json.loads((child / REFERENCE_FILE).read_text(encoding='utf-8'))
    assert link['donor_task_id'] == donor.name and link['canonical_task_id'] == c.parent
    assert not (child / 'video_evidence').exists() and not (child / 'video_evidence.json').exists()
    assert all(p.read_bytes() == data for p, data in before.items())
    body = c.body.model_copy(update={'operation_id': uuid4(), 'context_revision': context['context_revision']})
    next_receipt = c.service.accept('alice', receipt.task_id, body, BackgroundTasks(), c.note)
    next_child = c.artifacts.find_task_dir(next_receipt.task_id)
    assert json.loads((next_child / REFERENCE_FILE).read_text(encoding='utf-8'))['donor_task_id'] == donor.name
    assert json.loads((next_child / 'source_reference.json').read_text(encoding='utf-8'))['parent_task_id'] == c.parent
    c.service.run_once(next_receipt.task_id, 'alice', c.note)
    assert c.note.generate_from_transcript.call_count == 2
    assert c.note.generate_from_transcript.call_args.kwargs['video_evidence'].frames[0].image_path == frame
    assert not c.note.generate_from_file.called
    assert all(p.read_bytes() == data for p, data in before.items())


def legacy(c, receipt, child):
    (child / REFERENCE_FILE).unlink()
    operation = json.loads((child / 'new_generation.json').read_text(encoding='utf-8'))['operation_id']
    with c.receipts.sessions() as db:
        row = db.get(SourceRequestDB, ('alice', operation))
        bound = json.loads(row.receipt_json)
        bound.pop('summary_visual_reference_sha256')
        row.receipt_json = json.dumps(bound)
    return operation


def test_legacy_saved_child_uses_accepted_selected_parent_without_migration(provenance):
    c, donor, frame, receipt, child = provenance
    legacy(c, receipt, child)
    before = {p: p.read_bytes() for folder in (donor, c.folder, child) for p in folder.rglob('*') if p.is_file()}
    context = c.service.context('alice', receipt.task_id)
    assert context['visual_evidence_version']
    assert not (child / REFERENCE_FILE).exists()
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize('damage', ['pointer', 'missing_pointer', 'frame', 'owner', 'canonical', 'deleted', 'chain', 'receipt'])
def test_changed_visual_provenance_never_uses_canonical_or_rescans(provenance, damage):
    c, donor, frame, receipt, child = provenance
    if damage == 'pointer':
        value = json.loads((child / REFERENCE_FILE).read_text(encoding='utf-8')); value['source_version'] = '0' * 64
        c.artifacts.write_json(child / REFERENCE_FILE, value)
    elif damage == 'missing_pointer': (child / REFERENCE_FILE).unlink()
    elif damage == 'frame': frame.write_bytes(b'changed')
    elif damage == 'owner': (donor / 'recording_owner').write_text('bob')
    elif damage == 'canonical':
        value = json.loads((donor / 'source_reference.json').read_text(encoding='utf-8')); value['parent_task_id'] = str(uuid4())
        c.artifacts.write_json(donor / 'source_reference.json', value)
    elif damage == 'deleted': (donor / 'recording_deleted').write_text('deleted')
    elif damage == 'chain':
        (donor / 'video_evidence.json').unlink()
        c.artifacts.write_json(donor / REFERENCE_FILE, json.loads((child / REFERENCE_FILE).read_text(encoding='utf-8')))
    elif damage == 'receipt':
        operation = json.loads((child / 'new_generation.json').read_text(encoding='utf-8'))['operation_id']
        with c.receipts.sessions() as db: db.get(SourceRequestDB, ('alice', operation)).fingerprint = '0' * 64
    with pytest.raises(HTTPException) as error: c.service.context('alice', receipt.task_id)
    assert error.value.detail['code'] == 'summary_visual_evidence_unavailable'
    assert c.note.generate_from_transcript.call_count == 1


def test_legacy_changed_selected_context_is_not_authorized_by_disk_link(provenance):
    c, donor, frame, receipt, child = provenance
    legacy(c, receipt, child)
    value = json.loads((donor / 'transcript.json').read_text(encoding='utf-8'))
    value['metadata']['revision'] = 'changed after acceptance'
    c.artifacts.write_json(donor / 'transcript.json', value)
    with pytest.raises(HTTPException): c.service.context('alice', receipt.task_id)


def test_worker_rechecks_pointer_before_any_generation(provenance):
    c, donor, frame, receipt, child = provenance
    context = c.service.context('alice', receipt.task_id)
    body = c.body.model_copy(update={'operation_id': uuid4(), 'context_revision': context['context_revision']})
    next_receipt = c.service.accept('alice', receipt.task_id, body, BackgroundTasks(), c.note)
    staged = c.artifacts.find_task_dir(next_receipt.task_id)
    (staged / REFERENCE_FILE).unlink()
    c.service.run_once(next_receipt.task_id, 'alice', c.note)
    assert c.note.generate_from_transcript.call_count == 1
    assert json.loads((staged / 'status.json').read_text(encoding='utf-8'))['retryable'] is False


def test_missing_bound_pointer_cannot_be_replaced_by_a_new_child_cache(provenance):
    c, donor, frame, receipt, child = provenance
    images = child / 'video_evidence'; images.mkdir()
    other = images / 'frame.jpg'; Image.new('RGB', (10, 10), 'red').save(other)
    evidence = VideoEvidence(10, [VideoFrameEvidence(0, other, ['timeline'], [0, 9], 'other', 'recognized')], 10, True)
    video = VideoEvidenceService()
    video._save(child, evidence, video._identity(c.original, child.resolve(), 'alice'))
    (child / REFERENCE_FILE).unlink()
    with pytest.raises(HTTPException): c.service.context('alice', receipt.task_id)


@pytest.mark.parametrize('digest', ['missing', None, '', 'short', 'g' * 64, 'A' * 64, 7, [], {}])
def test_modern_visual_receipt_requires_valid_snapshot_digest(provenance, digest):
    c, donor, frame, receipt, child = provenance
    operation = json.loads((child / 'new_generation.json').read_text(encoding='utf-8'))['operation_id']
    with c.receipts.sessions() as db:
        row = db.get(SourceRequestDB, ('alice', operation))
        bound = json.loads(row.receipt_json)
        assert bound['summary_visual_reference_sha256']
        if digest == 'missing': bound.pop('summary_snapshot_sha256')
        else: bound['summary_snapshot_sha256'] = digest
        row.receipt_json = json.dumps(bound)
    snapshot = json.loads((child / 'model_source_snapshot.json').read_text(encoding='utf-8'))
    snapshot['llm_model'] = 'changed-without-accepted-snapshot'
    c.artifacts.write_json(child / 'model_source_snapshot.json', snapshot)
    with pytest.raises(HTTPException) as error: c.service.context('alice', receipt.task_id)
    assert error.value.detail['code'] == 'summary_visual_evidence_unavailable'
    assert c.note.generate_from_transcript.call_count == 1


def test_historical_self_owned_manifest_remains_readable_without_borrowing(provenance):
    """The real original A owns its frames; its old receipt has no snapshot hash."""
    c, donor, frame, receipt, child = provenance
    legacy(c, receipt, child)  # Saved HTML still has a valid snapshot digest.
    # Build an actual pre-presentation accepted intent, rather than merely
    # deleting modern fields from an intent whose context hash was different.
    from app.services.meeting_summary_regeneration import SummaryConfirmation, _digest, _submission
    from app.services.source_request_service import _fingerprint
    (c.folder / 'video_evidence.json').unlink()
    original = c.service.context('alice', c.parent)
    old_context = {key: original[key] for key in ('protocol', 'parent_task_id', 'canonical_task_id',
        'workflow', 'source', 'transcript_version', 'requires_confirmation', 'can_regenerate_summary')}
    revision = _digest({'owner': 'alice', 'context': old_context,
        'request': json.loads((c.folder / 'request.json').read_text(encoding='utf-8')),
        'snapshot': c.snapshot, 'source_reference': None})
    link = json.loads((donor / 'new_generation.json').read_text(encoding='utf-8'))
    for key in ('content_depth', 'presentation', 'connection_id'):
        assert link.pop(key) is None
    link['context_revision'] = revision
    c.artifacts.write_json(donor / 'new_generation.json', link)
    c.artifacts.write_text(donor / 'summary_generation_started', 'claimed')
    with c.receipts.sessions() as db:
        row = db.get(SourceRequestDB, ('alice', link['operation_id']))
        bound = json.loads(row.receipt_json)
        bound.pop('summary_snapshot_sha256')
        bound.pop('summary_visual_reference_sha256')
        row.receipt_json = json.dumps(bound)
        row.fingerprint = _fingerprint(_submission(c.parent, SummaryConfirmation(**{
            key: link[key] for key in SummaryConfirmation.model_fields if key in link})))
    before = {p: p.read_bytes() for folder in (donor, child, c.folder) for p in folder.rglob('*') if p.is_file()}
    assert c.service.context('alice', donor.name)['visual_evidence_version']
    assert c.service.context('alice', receipt.task_id)['visual_evidence_version']
    assert all(p.read_bytes() == value for p, value in before.items())
