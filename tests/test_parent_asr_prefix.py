"""Offline donor-helper tests, not proof of an integrated resume endpoint."""
import hashlib
import json
import socket
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from tests.test_independent_asr_namespace import audio_case, tmp_path, _EMPTY_PROOF, identity
from tests.test_new_generation_operation import case, accept
from app.db_models import SourceRequestDB
from app.services.asr_checkpoint_lock import checkpoint_lock
from app.services.task_model_source import SNAPSHOT_FILE
from app.transcribers.vilab_transcriber import _CheckpointEvidenceUnavailable


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('No provider or network call is allowed')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


@pytest.fixture
def resumed(audio_case):
    c = audio_case
    receipt, _ = accept(c)
    parent = c.artifacts.find_task_dir(receipt.task_id)
    stamps = []
    from app.services.asr_execution_binding import current_execution
    c.service.run_once(receipt.task_id, 'alice', lambda *_: stamps.append(current_execution().stamp()))
    assert len(stamps) == 1
    c.artifacts.update_status(parent, 'failed', 'provider failed', retryable=False)
    folder = parent / 'transcription_chunks' / 'vilab_stream'
    folder.mkdir(parents=True)
    digest = identity(c.wav)
    parts = [c.parts[0], {'start': 1, 'end': 2, 'text': '', 'segments': [],
             'language': 'zh', 'recognition_outcome': 'provider_terminal_empty',
             'terminal_evidence': {**_EMPTY_PROOF, 'untrusted': 'discard'}}]
    record = {'completed': parts, 'execution': {**stamps[0], 'normalized_identity': digest},
              'inflight': {'start_frame': 32000, 'end_frame': 48000},
              'plan': {'never': 'copy'}, 'session_limit': {'never': 'copy'}}
    c.artifacts.write_json(folder / 'recognition.json', record)
    # New explicit intent and DB receipt are real, but no new worker is run.
    from app.services.parent_asr_prefix import prefix_submission
    link = {'version': 2, 'operation_id': str(uuid.uuid4()), 'parent_task_id': receipt.task_id,
            'canonical_task_id': c.parent, 'context_revision': 'a' * 64,
            'source_version': c.confirmation.source_version,
            'parent_prefix': {'checkpoint_sha256': hashlib.sha256((folder / 'recognition.json').read_bytes()).hexdigest(),
                              'confirmed_end_frame': 32000}}
    child_receipt = c.receipts.reserve('alice', link['operation_id'], prefix_submission(link))
    child = c.artifacts.create_task_dir(child_receipt.task_id)
    for name, text in [('recording_owner', 'alice'), ('.task_id', child_receipt.task_id),
                       ('new_generation_started', 'claimed')]:
        (child / name).write_text(text, encoding='utf-8')
    c.artifacts.write_json(child / 'new_generation.json', link)
    c.artifacts.write_json(child / SNAPSHOT_FILE, c.snapshot)
    c.artifacts.write_json(child / 'source_reference.json', {
        'version': 1, 'owner': 'alice', 'parent_task_id': c.parent,
        'source_version': c.confirmation.source_version})
    c.receipts.accept('alice', link['operation_id'], child_receipt.task_id, status='preparing')
    return SimpleNamespace(c=c, parent=parent, donor=folder, record=record, link=link,
        child=child, child_receipt=child_receipt, parent_receipt=receipt, digest=digest)


def read(r):
    from app.services.parent_asr_prefix import locked_parent_prefix
    return locked_parent_prefix(r.c.receipts, r.c.artifacts, owner='alice',
        task_id=r.child_receipt.task_id, normalized_identity=r.digest, total_frames=48000)


def test_parent_prefix_preserves_extra_confirmed_audio_and_typed_empty_without_unknown_state(resumed):
    r = resumed
    before = {p: p.read_bytes() for p in r.parent.rglob('*') if p.is_file()}
    global_before = (r.c.donor / 'recognition.json').read_bytes()
    with read(r) as seed:
        assert seed['completed'][-1]['end'] == 2  # Global donor ends at 1.
        assert seed['completed'][1]['terminal_evidence'] == _EMPTY_PROOF
        assert seed['completed'][1]['recognition_outcome'] == 'provider_terminal_empty'
        assert set(seed) == {'completed', 'seed'}
        assert seed['seed']['donor_task_id'] == r.parent_receipt.task_id
        assert seed['seed']['confirmed_end_frame'] == 32000
        assert seed['seed']['checkpoint_sha256'] == hashlib.sha256(before[r.donor / 'recognition.json']).hexdigest()
        with pytest.raises(ValueError):
            with checkpoint_lock(r.donor):
                pytest.fail('Parent lock must survive until remaining submissions finish')
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert (r.c.donor / 'recognition.json').read_bytes() == global_before
    r.c.token.assert_not_called()
    r.c.recognize.assert_not_called()


@pytest.mark.parametrize('damage', [
    'child_reserved', 'child_db_missing', 'child_fingerprint', 'child_db_task',
    'parent_reserved', 'parent_db_missing', 'parent_fingerprint', 'parent_db_task',
    'owner', 'mapping', 'child_mapping', 'source', 'source_version', 'model', 'origin',
    'canonical', 'chain', 'active_status', 'missing_status', 'no_execution_marker',
    'stamp_owner', 'stamp_operation', 'stamp_task', 'stamp_parent', 'stamp_source',
    'stamp_snapshot', 'stamp_revision', 'normalized_identity', 'missing_execution',
    'corrupt', 'missing_checkpoint', 'uncommitted', 'legacy_sentinel', 'gap', 'overlap',
    'empty_proof', 'empty_text', 'boolean_frame', 'missing_prefix', 'unknown_parent_link',
    'child_owner', 'child_reference', 'canonical_mapping', 'manifest_hash', 'source_deleted',
    'marker_content', 'child_marker_content', 'boolean_stamp_version',
])
def test_invalid_parent_or_new_intent_blocks_instead_of_using_shorter_global(resumed, damage):
    r, c = resumed, resumed.c
    if damage.startswith('child_') and damage in {'child_reserved', 'child_db_missing', 'child_fingerprint', 'child_db_task'}:
        with c.sessions() as db:
            row = db.get(SourceRequestDB, ('alice', r.link['operation_id']))
            if damage == 'child_reserved': row.state = 'reserved'
            elif damage == 'child_db_missing': db.delete(row)
            elif damage == 'child_fingerprint': row.fingerprint = '0' * 64
            else: row.task_id = c.parent
    elif damage in {'parent_reserved', 'parent_db_missing', 'parent_fingerprint', 'parent_db_task'}:
        with c.sessions() as db:
            row = db.get(SourceRequestDB, ('alice', r.parent_receipt.operation_id))
            if damage == 'parent_reserved': row.state = 'reserved'
            elif damage == 'parent_db_missing': db.delete(row)
            elif damage == 'parent_fingerprint': row.fingerprint = '0' * 64
            else: row.task_id = c.parent
    elif damage == 'owner': (r.parent / 'recording_owner').write_text('bob')
    elif damage == 'mapping': (r.parent / '.task_id').write_text(c.parent)
    elif damage == 'child_mapping': (r.child / '.task_id').write_text(c.parent)
    elif damage == 'child_owner': (r.child / 'recording_owner').write_text('bob')
    elif damage == 'child_reference':
        c.artifacts.write_json(r.child / 'source_reference.json', {'version': 1,
            'owner': 'alice', 'parent_task_id': r.parent_receipt.task_id,
            'source_version': c.confirmation.source_version})
    elif damage == 'canonical_mapping': (c.folder / '.task_id').write_text(r.parent_receipt.task_id)
    elif damage == 'manifest_hash':
        manifest = json.loads((c.folder / 'source_media.json').read_text())
        c.artifacts.write_json(c.folder / 'source_media.json', {**manifest, 'sha256': '0' * 64})
    elif damage == 'source_deleted': (c.folder / 'recording_deleted').write_text('deleted')
    elif damage == 'marker_content': (r.parent / 'new_generation_started').write_text('not claimed')
    elif damage == 'child_marker_content': (r.child / 'new_generation_started').write_text('not claimed')
    elif damage == 'source': c.original.write_bytes(b'changed!')
    elif damage in {'model', 'origin'}:
        c.artifacts.write_json(r.parent / SNAPSHOT_FILE, {**c.snapshot,
            'asr_model' if damage == 'model' else 'server_url': 'other'})
    elif damage in {'source_version', 'canonical', 'chain'}:
        ref = json.loads((r.parent / 'source_reference.json').read_text())
        ref['source_version' if damage == 'source_version' else 'parent_task_id'] = (
            '0' * 64 if damage == 'source_version' else r.child_receipt.task_id)
        c.artifacts.write_json(r.parent / 'source_reference.json', ref)
    elif damage == 'active_status': c.artifacts.write_json(r.parent / 'status.json', {'status': 'transcribing'})
    elif damage == 'missing_status': (r.parent / 'status.json').unlink()
    elif damage == 'no_execution_marker': (r.parent / 'new_generation_started').unlink()
    elif damage.startswith('stamp_'):
        key = {'owner': 'owner', 'operation': 'operation_id', 'task': 'task_id',
               'parent': 'parent_task_id', 'source': 'source_version',
               'snapshot': 'snapshot_sha256', 'revision': 'context_revision'}[damage[6:]]
        r.record['execution'][key] = 'forged'
    elif damage == 'normalized_identity': r.record['execution']['normalized_identity'] = '0' * 64
    elif damage == 'missing_execution': del r.record['execution']
    elif damage == 'boolean_stamp_version': r.record['execution']['version'] = True
    elif damage == 'corrupt': (r.donor / 'recognition.json').write_text('{')
    elif damage == 'missing_checkpoint': (r.donor / 'recognition.json').unlink()
    elif damage == 'uncommitted': (r.donor / 'recognition.tmp').write_bytes(b'unknown')
    elif damage == 'legacy_sentinel': (r.donor / 'recognition.lock').write_bytes(b'unknown')
    elif damage == 'gap': r.record['completed'][1]['start'] = 1.5
    elif damage == 'overlap': r.record['inflight']['start_frame'] = 16000
    elif damage == 'empty_proof': r.record['completed'][1]['terminal_evidence']['inputComplete'] = False
    elif damage == 'empty_text': r.record['completed'][1]['text'] = 'invented'
    elif damage == 'boolean_frame': r.record['completed'][0]['start'] = False
    elif damage == 'missing_prefix': r.record['completed'] = []
    elif damage == 'unknown_parent_link':
        link = json.loads((r.parent / 'new_generation.json').read_text())
        c.artifacts.write_json(r.parent / 'new_generation.json', {**link, 'donor_path': 'arbitrary'})
    if damage.startswith('stamp_') or damage in {'normalized_identity', 'missing_execution', 'gap',
            'overlap', 'empty_proof', 'empty_text', 'boolean_frame', 'missing_prefix', 'boolean_stamp_version'}:
        c.artifacts.write_json(r.donor / 'recognition.json', r.record)
    before = {p: p.read_bytes() for p in r.parent.rglob('*') if p.is_file()}
    with pytest.raises(_CheckpointEvidenceUnavailable):
        with read(r):
            pytest.fail('Invalid donor must never become a usable seed')
    assert all(p.read_bytes() == raw for p, raw in before.items())
    c.token.assert_not_called()
    c.recognize.assert_not_called()


def test_locked_parent_never_falls_back(resumed):
    with checkpoint_lock(resumed.donor), pytest.raises(_CheckpointEvidenceUnavailable):
        with read(resumed):
            pytest.fail('No fallback while parent is busy')


def test_duplicate_operation_cannot_change_direct_parent_or_queue(resumed):
    from app.services.parent_asr_prefix import prefix_submission
    r = resumed
    same = r.c.receipts.reserve('alice', r.link['operation_id'], prefix_submission(r.link))
    assert not same.created and same.task_id == r.child_receipt.task_id
    with pytest.raises(HTTPException) as failure:
        r.c.receipts.reserve('alice', r.link['operation_id'], prefix_submission(
            {**r.link, 'parent_task_id': str(uuid.uuid4())}))
    assert failure.value.status_code == 409
    r.c.recognize.assert_not_called()


def test_different_normalized_wav_does_not_accept_parent_evidence(resumed):
    from app.services.parent_asr_prefix import locked_parent_prefix
    r = resumed
    with pytest.raises(_CheckpointEvidenceUnavailable):
        with locked_parent_prefix(r.c.receipts, r.c.artifacts, owner='alice',
                task_id=r.child_receipt.task_id, normalized_identity='0' * 64, total_frames=48000):
            pytest.fail('Different WAV must not inherit recognition')


def test_consumer_error_is_not_hidden_and_releases_parent_lock(resumed):
    with pytest.raises(RuntimeError, match='consumer failure'):
        with read(resumed):
            raise RuntimeError('consumer failure')
    with checkpoint_lock(resumed.donor):
        pass


def test_v2_parent_is_verified_without_following_execution_ancestry(resumed):
    from app.services.parent_asr_prefix import prefix_submission
    r, c = resumed, resumed.c
    # Build the next generation using synthetic checkpoint evidence. This tests
    # v2 receipt/stamp compatibility, not production claim or provider execution.
    parent = r.child
    c.artifacts.update_status(parent, 'failed', 'offline fixture')
    donor = parent / 'transcription_chunks' / 'vilab_stream'
    donor.mkdir(parents=True)
    stamp = {'version': 1, 'owner': 'alice', 'task_id': r.child_receipt.task_id,
        **{key: r.link[key] for key in ('operation_id', 'parent_task_id', 'source_version', 'context_revision')},
        'snapshot_sha256': hashlib.sha256(json.dumps(c.snapshot, sort_keys=True).encode()).hexdigest(),
        'normalized_identity': r.digest}
    c.artifacts.write_json(donor / 'recognition.json', {**r.record, 'execution': stamp})
    link = {**r.link, 'operation_id': str(uuid.uuid4()), 'parent_task_id': r.child_receipt.task_id}
    link['parent_prefix'] = {'checkpoint_sha256': hashlib.sha256((donor / 'recognition.json').read_bytes()).hexdigest(),
                             'confirmed_end_frame': 32000}
    claim = c.receipts.reserve('alice', link['operation_id'], prefix_submission(link))
    child = c.artifacts.create_task_dir(claim.task_id)
    for name, text in [('recording_owner', 'alice'), ('.task_id', claim.task_id),
                       ('new_generation_started', 'claimed')]:
        (child / name).write_text(text, encoding='utf-8')
    c.artifacts.write_json(child / 'new_generation.json', link)
    c.artifacts.write_json(child / SNAPSHOT_FILE, c.snapshot)
    c.artifacts.write_json(child / 'source_reference.json', json.loads((parent / 'source_reference.json').read_text()))
    c.receipts.accept('alice', link['operation_id'], claim.task_id, status='preparing')
    (r.parent / 'new_generation.json').write_text('{unreadable ancestor')
    newer = SimpleNamespace(c=c, child_receipt=claim, digest=r.digest)
    with read(newer) as seed:
        assert seed['seed']['donor_task_id'] == r.child_receipt.task_id
        assert seed['seed']['confirmed_end_frame'] == 32000


@pytest.mark.parametrize('target', ['checkpoint', 'chunks', 'process_lock', 'parent_owner'])
def test_symlinks_are_rejected_even_when_target_is_valid(resumed, target):
    r = resumed
    path = {'checkpoint': r.donor / 'recognition.json', 'chunks': r.parent / 'transcription_chunks',
            'process_lock': r.donor / 'recognition.process.lock',
            'parent_owner': r.parent / 'recording_owner'}[target]
    if not path.exists(): path.write_bytes(b'\0')
    destination = r.c.tmp_path / ('moved-' + path.name)
    path.rename(destination)
    try:
        path.symlink_to(destination, target_is_directory=destination.is_dir())
    except OSError:
        destination.rename(path)
        pytest.skip('Host cannot create symlinks')
    with pytest.raises(_CheckpointEvidenceUnavailable):
        with read(r):
            pytest.fail('No linked donor paths')
