"""Offline wire/storage/auth counterexamples; fixtures are not model acceptance."""
import copy
import hashlib
import json
import os
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db_models import SourceRequestDB
from app.routers.summary_visual import create_summary_visual_router
from app.services.meeting_summary_regeneration import SummaryConfirmation, _digest, _submission
from app.services.source_request_service import SourceRequestService
from app.services.summary_visual_artifact import (
    SIDECAR, SummaryVisualError, build_summary_visual, read_summary_visual,
    reviewed_visual_blocks, save_summary_visual, validate_summary_visual,
)
from app.services.task_artifact_service import TaskArtifactService


@pytest.fixture
def case(tmp_path, monkeypatch):
    # No provider, ASR, generation or shared runtime DB is touched.
    from app.services.vilab_cloud_service import VILabCloudService
    monkeypatch.setattr(VILabCloudService, 'request', lambda *a, **k: pytest.fail('no provider'))
    engine = create_engine('sqlite:///' + str(tmp_path / 'receipts.db'), connect_args={'check_same_thread': False})
    SourceRequestDB.__table__.create(engine)

    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as db, db.begin():
            yield db

    owner, task, parent = 'alice', str(uuid4()), str(uuid4())
    artifacts = TaskArtifactService(tmp_path / 'output')
    folder = artifacts.create_task_dir(task)
    body = SummaryConfirmation(operation_id=uuid4(), confirmed=True,
        context_revision='a' * 64, source_version='b' * 64,
        model_name='fixture-model', content_depth='brief', presentation='comic')
    receipts = SourceRequestService(sessions)
    receipts.reserve(owner, str(body.operation_id), _submission(parent, body), task_id=task)
    receipts.accept(owner, str(body.operation_id), task, status='preparing')
    snapshot = {'version': 1, 'owner': owner, 'mode': 'cloud',
                'server_url': 'https://fixture.invalid', 'asr_model': '',
                'llm_model': body.model_name, 'needs_stt': False}
    with sessions() as db:
        row = db.get(SourceRequestDB, (owner, str(body.operation_id)))
        row.receipt_json = json.dumps({'summary_snapshot_sha256': _digest(snapshot)})
    write = lambda name, value: (folder / name).write_bytes(json.dumps(value, ensure_ascii=False).encode('utf-8'))
    (folder / '.task_id').write_text(task)
    (folder / 'recording_owner').write_text(owner)
    (folder / 'summary_generation_started').write_text('claimed')
    write('model_source_snapshot.json', snapshot)
    write('new_generation.json', {'contract': 'meeting-summary-only-v1', 'parent_task_id': parent,
                                   **body.model_dump(mode='json')})
    write('summary_presentation.json', {'protocol': 1, 'task_id': task,
        'operation_id': str(body.operation_id), 'parent_task_id': parent,
        'source_version': body.source_version, 'model_name': body.model_name,
        'content_depth': 'brief', 'presentation': 'comic'})
    markdown = '# 原始模型测试正文\n\n设备 A < 设备 B，资料 http://example.test 尚待确认。\n'
    review = {'protocol': 3, 'blocks': [
        {'id': 'B0', 'markdown': '# 原始模型测试正文'},
        {'id': 'B1', 'markdown': '设备 A < 设备 B，资料 http://example.test 尚待确认。'}],
        'audit': [{'claim_id': 'C1', 'disposition': 'included', 'block_ids': ['B1']},
                  {'claim_id': 'C2', 'disposition': 'rejected', 'block_ids': [], 'reason': 'fixture'}]}
    write('meeting_fact_review.json', {'protocol': 1, 'raw_response': json.dumps(review, ensure_ascii=False)})
    write('status.json', {'status': 'success'})
    write('result.json', {'markdown': markdown})
    (folder / 'note.md').write_bytes(markdown.replace('\n', '\r\n').encode('utf-8'))
    (folder / 'screenshots').mkdir()
    screenshot = folder / 'screenshots' / 'summary-source-0.jpg'
    Image.new('RGB', (32, 24), 'white').save(screenshot, 'JPEG')
    wire = build_summary_visual(task_id=task, presentation='comic', markdown=markdown,
        blocks=reviewed_visual_blocks(review), frames=[{'id': 'F1', 'screenshot_index': 0,
            'timestamp_seconds': 1.25, 'grounded_label': '尚待确认'}],
        scenes=[{'id': 'S1', 'block_ids': ['B1'], 'frame_id': 'F1', 'grounded_label': '设备 A < 设备 B'}], diagram=None)
    yield SimpleNamespace(**locals())
    engine.dispose()


def save(c, wire=None):
    return save_summary_visual(c.artifacts, c.owner, c.task, c.markdown, wire or c.wire, sessions=c.sessions)


def read(c, owner=None, task=None):
    return read_summary_visual(c.artifacts, owner or c.owner, task or c.task, sessions=c.sessions)


def test_exact_utf8_body_hash_and_read_only_idempotency(case):
    c = case
    assert read(c) is None
    assert save(c) == c.wire
    path = c.folder / SIDECAR
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    assert save(c) == read(c) == c.wire
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert c.wire['body_sha256'] == hashlib.sha256(c.markdown.encode('utf-8')).hexdigest()
    # CRLF in physical note.md does not rewrite the JSON/API saved-body string.
    assert b'\r\n' in (c.folder / 'note.md').read_bytes()


@pytest.mark.parametrize('change', [
    lambda x: x.update(visual_protocol=True),
    lambda x: x.update(body_sha256='0' * 64),
    lambda x: x.update(task_id=str(uuid4())),
    lambda x: x.update(resource='https://example.test/x.jpg'),
    lambda x: x.pop('diagram'),
    lambda x: x['frames'][0].update(screenshot_index=True),
    lambda x: x['frames'][0].update(screenshot_index=8),
    lambda x: x['frames'][0].update(timestamp_seconds=float('nan')),
    lambda x: x['frames'][0].update(timestamp_seconds=10 ** 400),
    lambda x: x['frames'][0].update(timestamp_seconds=-1),
    lambda x: x['frames'][0].update(path='../other.jpg'),
    lambda x: x['frames'].append({**x['frames'][0], 'id': 'F2'}),
    lambda x: x['scenes'][0].update(frame_id='F2'),
    lambda x: x['scenes'][0].update(block_ids=['B0']),
    lambda x: x['scenes'][0].update(block_ids=['B1', 'B1']),
    lambda x: x['scenes'][0].update(grounded_label='没有根据'),
    lambda x: x['frames'][0].update(grounded_label='没有根据'),
    lambda x: x['scenes'][0].update(grounded_label='尚待确认\n'),
    lambda x: x['blocks'][1].update(text='不在原文'),
    lambda x: x['blocks'][1].update(claim_ids=['C1', 'C1']),
    lambda x: x['blocks'].append(x['blocks'][0]),
    lambda x: x.update(scenes=[]),
    lambda x: x.update(diagram={}),
])
def test_closed_wire_rejects_unbound_or_invalid_data(case, change):
    c = case
    wire = copy.deepcopy(c.wire)
    change(wire)
    with pytest.raises((SummaryVisualError, ValueError, TypeError)):
        validate_summary_visual(wire, task_id=c.task, presentation='comic', markdown=c.markdown)


def test_wire_size_is_utf8_not_character_count(case):
    c = case
    wire = copy.deepcopy(c.wire)
    wire['blocks'] = [{'id': f'B{i}', 'text': '汉' * 6000, 'claim_ids': ['C1']} for i in range(8)]
    with pytest.raises(SummaryVisualError):
        validate_summary_visual(wire, task_id=c.task, presentation='comic', markdown=c.markdown)


def infographic(c, kind='relationship'):
    return build_summary_visual(task_id=c.task, presentation='infographic', markdown=c.markdown,
        blocks=c.wire['blocks'], frames=[], scenes=[], diagram={'kind': kind,
        'nodes': [{'id': 'N1', 'block_ids': ['B1'], 'grounded_label': '设备 A'}],
        'edges': [{'id': 'E1', 'from': 'N1', 'to': 'N1', 'block_ids': ['B1'], 'grounded_label': '尚待确认'}]})


def test_relationship_self_loop_and_literal_url_are_not_removed(case):
    c = case
    wire = infographic(c)
    wire['diagram']['edges'][0]['grounded_label'] = 'http://example.test'
    assert validate_summary_visual(wire, task_id=c.task, presentation='infographic', markdown=c.markdown) == wire
    assert wire['diagram']['edges'][0]['from'] == wire['diagram']['edges'][0]['to']


@pytest.mark.parametrize('kind', ['cards', 'comparison'])
def test_non_relational_diagrams_reject_edges(case, kind):
    with pytest.raises(SummaryVisualError):
        infographic(case, kind)


@pytest.mark.parametrize('mutation', ['pending', 'unknown', 'owner', 'task', 'fingerprint', 'snapshot'])
def test_receipt_is_authority_not_disk_metadata(case, mutation):
    c = case
    save(c)
    with c.sessions() as db:
        row = db.get(SourceRequestDB, (c.owner, str(c.body.operation_id)))
        if mutation in ('pending', 'unknown'):
            row.state = mutation
        elif mutation == 'owner':
            row.owner = 'mallory'
        elif mutation == 'task':
            row.task_id = str(uuid4())
        elif mutation == 'fingerprint':
            row.fingerprint = 'f' * 64
        else:
            row.receipt_json = '{}'
    assert read(c) is None
    with pytest.raises(SummaryVisualError):
        save(c)


@pytest.mark.parametrize('filename', ['recording_owner', '.task_id', 'summary_generation_started',
                                     'summary_presentation.json', 'model_source_snapshot.json'])
def test_tampered_identity_or_frozen_metadata_is_not_read(case, filename):
    c = case
    save(c)
    (c.folder / filename).write_bytes(b'changed')
    assert read(c) is None


@pytest.mark.parametrize('state', ['summarizing', 'failed', 'unknown'])
def test_unfinished_graphic_does_not_become_success(case, state):
    c = case
    save(c)
    c.write('status.json', {'status': state})
    assert read(c) is None


def test_changed_saved_body_including_trailing_newline_is_rejected(case):
    c = case
    save(c)
    c.write('result.json', {'markdown': c.markdown.rstrip()})
    assert read(c) is None


def test_review_claims_are_projected_and_cannot_be_self_reported(case):
    c = case
    assert c.wire['blocks'][0]['claim_ids'] == []
    assert c.wire['blocks'][1]['claim_ids'] == ['C1']
    changed = copy.deepcopy(c.wire)
    changed['blocks'][1]['claim_ids'] = ['C2']
    with pytest.raises(SummaryVisualError):
        save(c, changed)
    assert not (c.folder / SIDECAR).exists()


def test_changed_raw_review_is_not_another_finished_graphic(case):
    c = case
    save(c)
    c.write('meeting_fact_review.json', {'protocol': 1, 'raw_response': 'partial draft'})
    assert read(c) is None


def test_changed_screenshot_hash_and_png_disguised_as_jpeg_are_rejected(case):
    c = case
    save(c)
    Image.new('RGB', (32, 24), 'red').save(c.screenshot, 'JPEG')
    assert read(c) is None
    Image.new('RGB', (32, 24), 'white').save(c.screenshot, 'PNG')
    with pytest.raises(SummaryVisualError):
        save(c)


def test_foreign_task_and_owner_and_path_are_unavailable(case):
    c = case
    save(c)
    assert read(c, owner='mallory') is None
    assert read(c, task=str(uuid4())) is None
    assert read(c, task='../' + c.task) is None


def test_existing_sidecar_cannot_be_overwritten_with_new_content(case):
    c = case
    save(c)
    before = (c.folder / SIDECAR).read_bytes()
    wire = copy.deepcopy(c.wire)
    wire['frames'][0]['timestamp_seconds'] = 2
    with pytest.raises(SummaryVisualError):
        save(c, wire)
    assert (c.folder / SIDECAR).read_bytes() == before


def test_hardlinked_screenshot_is_rejected(case, tmp_path):
    c = case
    os.link(c.screenshot, tmp_path / 'foreign.jpg')
    with pytest.raises(SummaryVisualError):
        save(c)


def test_jpeg_header_with_truncated_body_is_not_a_finished_frame(case):
    c = case
    c.screenshot.write_bytes(c.screenshot.read_bytes()[:-8])
    with pytest.raises((SummaryVisualError, OSError)):
        save(c)
    assert read(c) is None


def test_duplicate_json_keys_are_rejected_read_only(case):
    c = case
    path = c.folder / SIDECAR
    path.write_bytes(b'{"artifact_protocol":1,"artifact_protocol":1}')
    before = path.read_bytes()
    assert read(c) is None
    assert path.read_bytes() == before


def test_router_read_only_auth_and_no_store(case):
    c = case
    owner = ['alice']
    def principal():
        if owner[0] is None:
            raise HTTPException(401, 'login')
        return SimpleNamespace(user_id=owner[0])
    app = FastAPI()
    app.include_router(create_summary_visual_router(c.artifacts, principal, c.sessions), prefix='/api')
    client = TestClient(app)
    url = f'/api/task/{c.task}/summary-visual'
    missing = client.get(url)
    assert missing.status_code == 404 and 'no-store' in missing.headers['cache-control']
    save(c)
    response = client.get(url)
    assert response.status_code == 200 and response.json() == c.wire
    assert response.headers['vary'] == 'Cookie, Authorization'
    assert 'no-store' in response.headers['cache-control']
    assert set(response.json()) == set(c.wire)  # Private receipt/owner/hash manifest is not returned.
    assert client.post(url).status_code == 405
    owner[0] = 'mallory'
    assert client.get(url).status_code == 404
    owner[0] = None
    assert client.get(url).status_code == 401


def test_fresh_asr_receipt_projection_reads_without_provider_or_current_connection(case, monkeypatch):
    from app.services.source_request_service import _fingerprint
    from app.services.task_fresh_asr import _submission as fresh_submission
    from app.services.vilab_connection_service import VILabConnectionService
    c = case
    # Historical artifact authentication uses only its accepted receipt, never
    # the present connection/keychain/catalog. It does not execute fresh ASR.
    monkeypatch.setattr(VILabConnectionService, 'validate_snapshot',
                        lambda *a, **k: pytest.fail('must not authorize current connection'))
    link = {'contract': 'meeting-fresh-asr-v1', 'parent_task_id': c.parent,
        'canonical_task_id': c.parent, 'snapshot_sha256': _digest(c.snapshot),
        'operation_id': str(c.body.operation_id), 'confirmed': True, 'asr_mode': 'fresh',
        'llm_mode': 'select', 'extra_asr_consent': True, 'context_revision': 'a' * 64,
        'fresh_context_revision': 'c' * 64, 'selection_revision': 'd' * 64,
        'source_version': c.body.source_version, 'asr_model': 'fixture-asr',
        'model_name': c.body.model_name, 'connection_id': None,
        'content_depth': 'brief', 'presentation': 'comic'}
    c.write('new_generation.json', link)
    (c.folder / 'summary_generation_started').unlink()
    (c.folder / 'new_generation_started').write_text('claimed')
    with c.sessions() as db:
        row = db.get(SourceRequestDB, (c.owner, str(c.body.operation_id)))
        row.fingerprint = _fingerprint(fresh_submission(link))
    save(c)
    assert read(c) == c.wire
    link['snapshot_sha256'] = '0' * 64
    c.write('new_generation.json', link)
    assert read(c) is None


def test_failed_atomic_publication_never_creates_a_finished_sidecar(case, monkeypatch):
    c = case
    def denied(*args):
        raise OSError('offline publication interruption')
    monkeypatch.setattr(os, 'link', denied)
    with pytest.raises(OSError):
        save(c)
    assert not (c.folder / SIDECAR).exists()
    assert not list(c.folder.glob('.summary_visual.*.tmp'))
    assert read(c) is None


def test_read_detects_file_replaced_between_lstat_and_open(case, monkeypatch):
    from app.services import summary_visual_artifact as module
    c = case
    save(c)
    original = module.os.fstat
    def replaced(fd):
        info = original(fd)
        values = {key: getattr(info, key) for key in (
            'st_mode', 'st_nlink', 'st_size', 'st_dev', 'st_ino', 'st_mtime_ns', 'st_ctime_ns')}
        values['st_ino'] += 1
        return SimpleNamespace(**values)
    monkeypatch.setattr(module.os, 'fstat', replaced)
    assert read(c) is None


@pytest.mark.parametrize('single', [True, False])
def test_boundary_projection_matches_actual_successful_fact_finalizer(single):
    from app.llm.meeting_fact_material import prepare_fact_material, finalize_fact_review
    from app.llm.meeting_presentation import presentation_scope
    from app.llm.source_references import bind_source_references
    from app.models.transcript import TranscriptSegment
    source = 'Keep the green latch closed until noon.'
    material = {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Latch'}], 'claims': [
        {'id': 'C1', 'topic_id': 'T1', 'field': 'condition', 'text': source, 'material': True,
         'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': source}]}]}
    if single:
        raw_blocks = [{'id': 'B1', 'markdown': '\n\t  ' + source + '\n\t '}]
        expected = [source]
    else:
        raw_blocks = [{'id': 'H1', 'markdown': '\n\t # Latch  '},
                      {'id': 'B1', 'markdown': '\n' + source + '  \n'},
                      {'id': 'B2', 'markdown': '  Keep  internal spacing.\n\t '}]
        expected = ['# Latch  ', '\n' + source + '  \n', '  Keep  internal spacing.']
    review = {'protocol': 3, 'blocks': raw_blocks, 'figures': [],
              'audit': [{'claim_id': 'C1', 'disposition': 'included', 'block_ids': ['B1']}]}
    before = copy.deepcopy(review)
    raw = json.dumps(review)
    with bind_source_references([TranscriptSegment(0, 10, source)]), presentation_scope('brief', 'text'):
        checked = prepare_fact_material(json.dumps(material), source, require_protocol=3)
        markdown = finalize_fact_review(raw, checked, source)
    projected = reviewed_visual_blocks(review)
    wire = build_summary_visual(task_id=str(uuid4()), presentation='infographic', markdown=markdown,
        blocks=projected, frames=[], scenes=[], diagram={'kind': 'cards', 'edges': [],
        'nodes': [{'id': 'N1', 'block_ids': ['B1'], 'grounded_label': source}]})
    assert [block['text'] for block in projected] == expected
    assert all(block['text'] in markdown for block in wire['blocks'])
    assert wire['body_sha256'] == hashlib.sha256(markdown.encode('utf-8')).hexdigest()
    assert review == before and json.dumps(review) == raw


def test_boundary_projection_save_read_preserves_raw_review_bytes_and_hash(case):
    c = case
    review = copy.deepcopy(c.review)
    review['blocks'][0]['markdown'] = '\n\t ' + review['blocks'][0]['markdown']
    review['blocks'][-1]['markdown'] += '\n'
    markdown = '\n\n'.join(block['markdown'] for block in review['blocks']).strip()
    raw = json.dumps(review, ensure_ascii=False)
    c.write('meeting_fact_review.json', {'protocol': 1, 'raw_response': raw})
    review_path = c.folder / 'meeting_fact_review.json'
    original_bytes = review_path.read_bytes()
    wire = build_summary_visual(task_id=c.task, presentation='comic', markdown=markdown,
        blocks=reviewed_visual_blocks(review), frames=c.wire['frames'], scenes=c.wire['scenes'], diagram=None)
    c.write('result.json', {'markdown': markdown})
    save_summary_visual(c.artifacts, c.owner, c.task, markdown, wire, sessions=c.sessions)
    assert read(c) == wire
    payload = json.loads((c.folder / SIDECAR).read_bytes())
    assert payload['review_sha256'] == hashlib.sha256(original_bytes).hexdigest()
    assert payload['visual']['body_sha256'] == hashlib.sha256(markdown.encode('utf-8')).hexdigest()
    assert review_path.read_bytes() == original_bytes
    assert json.loads(original_bytes)['raw_response'] == raw
    assert review['blocks'][0]['markdown'].startswith('\n\t ')
    assert review['blocks'][-1]['markdown'].endswith('\n')


def final_ledger_case(c, presentation='comic'):
    """Prepare a real validated raw4 envelope in this fixture's accepted task."""
    from app.llm.meeting_final_review import finalize_final_review
    from app.llm.meeting_presentation import presentation_scope
    from app.llm.video_material import bind_video_material
    from app.services.source_request_service import _fingerprint
    from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence
    blocks = copy.deepcopy(c.review['blocks'])
    blocks[0]['markdown'] = '\n\t ' + blocks[0]['markdown']
    blocks[-1]['markdown'] += '\n'
    evidence = [{'kind': 'frame_observation', 'source_ref': '[FRAME:0001]',
                 'observation': 'Synthetic independent document comparison, still uncertain.'}]
    material = {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic comparison'}], 'claims': [
        {'id': 'C1', 'topic_id': 'T1', 'field': 'relation', 'text': blocks[-1]['markdown'],
         'material': True, 'evidence': evidence}]}
    claims = [{'id': 'C1', 'field': 'relation', 'text': blocks[-1]['markdown'], 'material': True,
               'disposition': 'included', 'block_ids': ['B1'], 'evidence': evidence}]
    frames = [{**c.wire['frames'][0], 'id': '[FRAME:0001]'}] if presentation == 'comic' else []
    scenes = [{**c.wire['scenes'][0], 'frame_id': '[FRAME:0001]'}] if presentation == 'comic' else []
    diagram = None if presentation == 'comic' else {'kind': 'cards', 'edges': [],
        'nodes': [{'id': 'N1', 'block_ids': ['B1'], 'grounded_label': '尚待确认'}]}
    value = {'protocol': 4, 'blocks': blocks, 'claims': claims,
             'visual': {'scenes': scenes, 'diagram': diagram}}
    raw = json.dumps(value, ensure_ascii=False, indent=2)
    video = VideoEvidence(5, [VideoFrameEvidence(1.25, c.screenshot, ['timeline'], [1.25])], 5, True)
    with presentation_scope('brief', presentation) as state, bind_video_material(video, {'vision': True}):
        markdown = finalize_final_review(raw, json.dumps(material))
        assert state.raw_review == raw and state.visual_review['review']['protocol'] == 4
    # A separate confirmed presentation choice needs its own accepted fingerprint.
    body = c.body.model_copy(update={'presentation': presentation})
    c.write('new_generation.json', {'contract': 'meeting-summary-only-v1', 'parent_task_id': c.parent,
                                   **body.model_dump(mode='json')})
    metadata = json.loads((c.folder / 'summary_presentation.json').read_bytes())
    c.write('summary_presentation.json', {**metadata, 'presentation': presentation})
    with c.sessions() as db:
        db.get(SourceRequestDB, (c.owner, str(body.operation_id))).fingerprint = _fingerprint(_submission(c.parent, body))
    c.write('meeting_fact_review.json', {'protocol': 1, 'raw_response': raw})
    c.write('result.json', {'markdown': markdown})
    wire = build_summary_visual(task_id=c.task, presentation=presentation, markdown=markdown,
        blocks=reviewed_visual_blocks(value), frames=frames, scenes=scenes, diagram=diagram)
    return markdown, wire, raw, value


@pytest.mark.parametrize('presentation', ['comic', 'infographic'])
def test_protocol_four_saved_reads_preserve_raw_origin_model_and_body_hashes(case, monkeypatch, presentation):
    c = case
    markdown, wire, raw, value = final_ledger_case(c, presentation)
    from app.services.vilab_cloud_service import VILabCloudService
    monkeypatch.setattr(VILabCloudService, 'connection_snapshot', lambda *a, **k: pytest.fail('read must not resolve a connection'))
    monkeypatch.setattr('app.services.windows_ocr.recognize_batch', lambda *a, **k: pytest.fail('read must not OCR'))
    path = c.folder / 'meeting_fact_review.json'
    before = path.read_bytes()
    assert save_summary_visual(c.artifacts, c.owner, c.task, markdown, wire, sessions=c.sessions) == wire
    assert read(c) == wire
    payload = json.loads((c.folder / SIDECAR).read_bytes())
    assert payload['review_sha256'] == hashlib.sha256(before).hexdigest()
    assert payload['receipt']['snapshot_sha256'] == _digest(c.snapshot)
    assert payload['visual']['body_sha256'] == hashlib.sha256(markdown.encode('utf-8')).hexdigest()
    assert path.read_bytes() == before and json.loads(before)['raw_response'] == raw
    assert json.loads(raw)['protocol'] == 4 and 'audit' not in json.loads(raw)
    assert value['blocks'][0]['markdown'].startswith('\n\t ')


@pytest.mark.parametrize('change', ['raw_whitespace', 'origin', 'model', 'fingerprint', 'body'])
def test_protocol_four_read_rejects_binding_mutations_without_new_execution(case, change):
    c = case
    markdown, wire, raw, _ = final_ledger_case(c)
    save_summary_visual(c.artifacts, c.owner, c.task, markdown, wire, sessions=c.sessions)
    if change == 'raw_whitespace':
        c.write('meeting_fact_review.json', {'protocol': 1, 'raw_response': raw + '\n'})
    elif change in {'origin', 'model'}:
        c.write('model_source_snapshot.json', {**c.snapshot,
            **({'server_url': 'https://other-origin.invalid'} if change == 'origin' else {'llm_model': 'other-model'})})
    elif change == 'fingerprint':
        with c.sessions() as db:
            db.get(SourceRequestDB, (c.owner, str(c.body.operation_id))).fingerprint = '0' * 64
    else:
        c.write('result.json', {'markdown': markdown + 'Changed'})
    assert read(c) is None


@pytest.mark.parametrize('change', ['wrong_final_source', 'different_plan', 'fenced_raw'])
def test_protocol_four_save_cannot_rebind_layout_or_sources_or_repair_a_fence(case, change):
    c = case
    markdown, wire, raw, value = final_ledger_case(c)
    if change == 'wrong_final_source':
        value['claims'][0]['evidence'][0]['source_ref'] = '[FRAME:9999]'
        raw = json.dumps(value)
    elif change == 'different_plan':
        value['visual']['scenes'][0]['grounded_label'] = '尚待确认'
        raw = json.dumps(value)
    else:
        raw = '```json\n' + raw + '\n```'
    c.write('meeting_fact_review.json', {'protocol': 1, 'raw_response': raw})
    with pytest.raises(SummaryVisualError):
        save_summary_visual(c.artifacts, c.owner, c.task, markdown, wire, sessions=c.sessions)
    assert not (c.folder / SIDECAR).exists()
