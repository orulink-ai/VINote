"""Offline production-boundary counterexamples for the private overlay."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.services import meeting_ocr_layout as layout
from app.services.video_evidence_service import VideoEvidenceError
from app.llm.video_material import bind_video_material
from app.llm.meeting_fact_protocol import _evidence
from test_meeting_source_bundle import source, llm_capture, run, source_events
from test_meeting_summary_regeneration import case, accept


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def material(folder, evidence, *, owner='alice', task='child', context=None):
    folder.mkdir(exist_ok=True)
    for name, value in [('recording_owner', owner), ('.task_id', task)]:
        (folder / name).write_text(value, encoding='utf-8')
    context = context or {'context_revision': 'context', 'source_version': 'source', 'snapshot_sha256': 'model'}
    items = []
    source_frames = []
    for f in evidence.frames:
        words = f.ocr_text.split(' ')
        items.append(dict(expected_sha256=sha(f.image_path.read_bytes()), status='recognized',
                          text=f.ocr_text, lines=[dict(text=w) for w in words if w]))
        source_frames.append(dict(sha256=items[-1]['expected_sha256'], timestamp=f.timestamp,
                                  sample_offsets=f.sample_offsets))
    payload = dict(protocol=1, kind='desktop_derived_ocr', owner=owner, task_id=task,
                   accepted_context_binding=context, status='completed', inputs_verified_after=True,
                   source_frames=source_frames, items=items)
    (folder / 'meeting_video_ocr.json').write_text(json.dumps(payload), encoding='utf-8')
    return context


@pytest.fixture
def prepared(source, tmp_path):
    ev = source.evidence
    for f in ev.frames:
        f.ocr_text = 'alpha beta'; f.ocr_status = 'recognized'
    folder = tmp_path / 'child'
    context = material(folder, ev)
    def freeze(**kwargs):
        return layout.freeze_layout(ev, task_dir=folder, owner='alice', task_id='child',
                                    context_binding=context, policy=kwargs.pop('policy', 1), **kwargs)
    return source, ev, folder, context, freeze


def test_real_vilab_two_stage_same_view_raw_guard_and_original_images(prepared, monkeypatch):
    src, ev, folder, _, freeze = prepared
    before = [f.ocr_text for f in ev.frames]
    frozen = freeze(); layout.attach_layout(ev, frozen, accepted_revision=frozen.revision)
    persisted = json.loads((folder / layout.FILE).read_text())
    assert persisted['frames'][0]['raw_text_sha256'] == sha('alpha beta'.encode())
    assert persisted['frames'][0]['view_sha256'] == sha('alpha\n beta'.encode())
    llm, calls, receipts = llm_capture(src, monkeypatch)
    run(src, llm)
    assert len(calls) == 2
    for call in calls:
        records = [r for _, r, _ in source_events(call['messages'][1]['content']) if r['source_ref'].startswith('[FRAME:')]
        assert len(records) == 4
        assert all(r['visible_text'] == 'alpha\n beta' and r['ocr_view_mode'] == 'insert_lf_v1' for r in records)
        assert sum(b['type'] == 'image_url' for b in call['messages'][1]['content']) == 4
    assert [f.ocr_text for f in ev.frames] == before
    assert receipts[0]['ocr_layout_sha256'] == receipts[1]['ocr_layout_sha256'] == frozen.sidecar_sha256
    assert receipts[0]['input_view_revision'] == receipts[1]['input_view_revision'] == frozen.revision
    assert receipts[0]['images'] == receipts[1]['images']
    assert 'raw visible_text' not in ev._text_header()
    assert 'raw OCR by removing LF only' in ev._text_header()
    with bind_video_material(ev, {'vision': True}):
        assert _evidence([{'kind': 'ocr_span', 'source_ref': '[FRAME:0001]', 'quote': 'alpha beta'}])
        with pytest.raises(ValueError):
            _evidence([{'kind': 'ocr_span', 'source_ref': '[FRAME:0001]', 'quote': 'alpha\n beta'}])


def test_text_only_receives_same_view_without_image_authority(prepared):
    _, ev, _, _, freeze = prepared
    frozen = freeze(); layout.attach_layout(ev, frozen, accepted_revision=frozen.revision)
    value = ev.user_content('Synthetic source', capabilities={'vision': False})
    assert isinstance(value, str) and 'alpha\\n beta' in value
    assert ev.input_receipt()['mode'] == 'ocr_only'
    with bind_video_material(ev, {'vision': False}):
        with pytest.raises(ValueError):
            _evidence([{'kind': 'frame_observation', 'source_ref': '[FRAME:0001]', 'observation': 'invented image'}])


@pytest.mark.parametrize('text,lines', [
    ('\U0001f600e\u0301 \u4e2d', ['\U0001f600e\u0301', '\u4e2d']),
    ('same same same', ['same', 'same', 'same']),
    ('  first\tsecond  ', ['first', 'second']),
])
def test_unicode_repeated_lines_and_all_original_whitespace(text, lines):
    spans, mode = layout._lines(text, {'status': 'recognized', 'text': text, 'lines': [{'text': s} for s in lines]})
    assert mode == 'insert_lf_v1'
    assert [text[a:b] for a, b in spans] == lines
    view = layout._view(text, spans)
    assert view.replace('\n', '') == text
    assert len(view) == len(text) + len(lines) - 1
    assert ''.join(c for c in view if not c.isspace()) == ''.join(c for c in text if not c.isspace())


@pytest.mark.parametrize('mutation', ['missing_lines', 'missing_line_text', 'partial', 'repeat_missing',
                                    'native_crlf', 'text_mismatch', 'bad_type', 'source_hash_mismatch'])
def test_bad_or_incomplete_layout_is_explicit_flat_not_partial(prepared, mutation):
    _, ev, folder, _, freeze = prepared
    path = folder / 'meeting_video_ocr.json'
    p = json.loads(path.read_text()); item = p['items'][0]
    if mutation == 'missing_lines': del item['lines']
    elif mutation == 'missing_line_text': item['lines'][0] = {}
    elif mutation == 'partial': item['lines'] = item['lines'][:1]
    elif mutation == 'repeat_missing': item['lines'].append({'text': 'alpha'})
    elif mutation == 'native_crlf':
        ev.frames[0].ocr_text = item['text'] = 'alpha\r\nbeta'
    elif mutation == 'text_mismatch': item['text'] = 'changed candidate'
    elif mutation == 'bad_type': item['lines'] = 'not an array'
    elif mutation == 'source_hash_mismatch': item['expected_sha256'] = '0' * 64
    path.write_text(json.dumps(p))
    frozen = freeze(); layout.attach_layout(ev, frozen, accepted_revision=frozen.revision)
    first = ev._frame_records()[0]
    assert first['ocr_view_mode'] == 'flat' and first['visible_text'] == ev.frames[0].ocr_text
    stored = json.loads((folder / layout.FILE).read_text())
    assert stored['frames'][0]['line_spans'] == []
    assert stored['frames'][1]['mode'] == 'insert_lf_v1'


@pytest.mark.parametrize('raw', [None, b'corrupt json', b'{"items":[],"items":[]}'])
def test_absent_or_unparseable_layout_keeps_explicit_flat(prepared, raw):
    _, ev, folder, _, freeze = prepared
    path = folder / 'meeting_video_ocr.json'
    if raw is None: path.unlink()
    else: path.write_bytes(raw)
    frozen = freeze(); layout.attach_layout(ev, frozen, accepted_revision=frozen.revision)
    assert all(r['ocr_view_mode'] == 'flat' and r['visible_text'] == 'alpha beta' for r in ev._frame_records())


@pytest.mark.parametrize('policy', [None, True, False, 1.0, '1', 0, 2])
def test_old_or_malformed_policy_cannot_freeze_new_view(prepared, policy):
    _, _, folder, _, freeze = prepared
    with pytest.raises(VideoEvidenceError): freeze(policy=policy)
    assert not (folder / layout.FILE).exists()


def test_old_revision_cannot_attach_layout(prepared):
    _, ev, _, _, freeze = prepared
    frozen = freeze()
    with pytest.raises(VideoEvidenceError):
        layout.attach_layout(ev, frozen, accepted_revision='old_material_revision')
    assert ev._ocr_layout is None


@pytest.mark.parametrize('changed', ['frame', 'raw_text', 'offsets', 'ocr_sidecar', 'layout_sidecar', 'owner', 'task'])
def test_mutation_between_calls_is_blocked_before_second_request(prepared, monkeypatch, changed):
    src, ev, folder, _, freeze = prepared
    frozen = freeze(); layout.attach_layout(ev, frozen, accepted_revision=frozen.revision)
    def mutate():
        if changed == 'frame': ev.frames[0].image_path.write_bytes(b'changed original')
        elif changed == 'raw_text': ev.frames[0].ocr_text = 'changed raw'
        elif changed == 'offsets': ev.frames[0].sample_offsets.append(3.14159)
        elif changed == 'ocr_sidecar': (folder / 'meeting_video_ocr.json').write_text('{}')
        elif changed == 'layout_sidecar': (folder / layout.FILE).write_text('{}')
        elif changed == 'owner': (folder / 'recording_owner').write_text('other')
        else: (folder / '.task_id').write_text('other')
    llm, calls, _ = llm_capture(src, monkeypatch, after_first=mutate)
    with pytest.raises(VideoEvidenceError): run(src, llm)
    assert len(calls) == 1


def test_over_budget_no_truncation_or_layout_write(prepared, monkeypatch):
    _, ev, folder, _, freeze = prepared
    monkeypatch.setattr(layout, '_MAX_VIEW_CHARS', sum(len(f.ocr_text) for f in ev.frames))
    with pytest.raises(VideoEvidenceError): freeze()
    assert not (folder / layout.FILE).exists()
    assert all(f.ocr_text == 'alpha beta' for f in ev.frames)


def setup_service(c, monkeypatch):
    from PIL import Image
    from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence
    from app.services import meeting_summary_regeneration as summary
    frame = c.folder / 'synthetic-frame.jpg'; Image.new('RGB', (10, 10)).save(frame)
    ev = VideoEvidence(10, [VideoFrameEvidence(0, frame, ['timeline'], [0], 'alpha beta', 'recognized')], 10, True)
    ev._summary_frame_hashes = {frame: sha(frame.read_bytes())}
    ev._summary_visual_donor_task_id = c.parent
    ev._summary_visual_manifest_sha256 = 'f' * 64
    monkeypatch.setattr(summary, 'retained_visual_evidence', lambda *a, **k: copy.deepcopy(ev))
    def prepared(evidence, *, task_dir, task_id, owner, context_binding):
        material(task_dir, evidence, owner=owner, task=task_id, context=context_binding)
        return evidence
    monkeypatch.setattr('app.services.meeting_video_ocr.prepare_meeting_video_ocr', prepared)
    context = c.service.context('alice', c.parent)
    c.body = c.body.model_copy(update={'context_revision': context['context_revision']})
    return ev


def test_actual_service_intake_binds_new_revision_before_note_service_and_does_not_replay(case, monkeypatch):
    c = case; setup_service(c, monkeypatch)
    receipt, _ = accept(c)
    c.service.run_once(receipt.task_id, 'alice', c.note)
    assert c.note.generate_from_transcript.call_count == 1
    actual = c.note.generate_from_transcript.call_args.kwargs['video_evidence']
    from app.db_models import SourceRequestDB
    with c.receipts.sessions() as db:
        row = db.get(SourceRequestDB, ('alice', str(c.body.operation_id)))
        saved = json.loads(row.receipt_json)
    assert saved['summary_ocr_layout_policy'] == 1
    assert saved['summary_input_view_revision'] == actual._ocr_layout.revision
    assert saved['summary_ocr_layout_sha256'] == actual._ocr_layout.sidecar_sha256
    assert actual._frame_records()[0]['visible_text'] == 'alpha\n beta'
    c.service.run_once(receipt.task_id, 'alice', c.note)
    assert c.note.generate_from_transcript.call_count == 1


def test_actual_service_legacy_receipt_remains_flat_and_not_migrated(case, monkeypatch):
    c = case; setup_service(c, monkeypatch)
    receipt, _ = accept(c)
    from app.db_models import SourceRequestDB
    with c.receipts.sessions() as db:
        row = db.get(SourceRequestDB, ('alice', str(c.body.operation_id)))
        saved = json.loads(row.receipt_json); del saved['summary_ocr_layout_policy']
        row.receipt_json = json.dumps(saved)
    # Existing operation acceptance is query-only, including under the new code.
    queried, _ = accept(c)
    assert queried.task_id == receipt.task_id
    c.service.run_once(receipt.task_id, 'alice', c.note)
    assert c.note.generate_from_transcript.call_count == 1
    actual = c.note.generate_from_transcript.call_args.kwargs['video_evidence']
    assert actual._ocr_layout is None and actual._frame_records()[0]['visible_text'] == 'alpha beta'
    assert 'ocr_view_mode' not in actual._frame_records()[0]
    with c.receipts.sessions() as db:
        assert json.loads(db.get(SourceRequestDB, ('alice', str(c.body.operation_id))).receipt_json) == saved
    assert not (c.artifacts.find_task_dir(receipt.task_id) / layout.FILE).exists()


@pytest.mark.parametrize('change', ['clear_policy', 'policy_true', 'owner_lookup', 'state', 'task', 'fingerprint', 'snapshot', 'old_revision'])
def test_receipt_rechecked_after_preparation_before_view_authorization(case, monkeypatch, change):
    c = case; setup_service(c, monkeypatch); receipt, _ = accept(c)
    from app.db_models import SourceRequestDB
    original = c.service._bind_layout_revision
    def changed(*args):
        with c.receipts.sessions() as db:
            row = db.get(SourceRequestDB, ('alice', str(c.body.operation_id)))
            saved = json.loads(row.receipt_json)
            if change == 'clear_policy': del saved['summary_ocr_layout_policy']
            elif change == 'policy_true': saved['summary_ocr_layout_policy'] = True
            elif change == 'owner_lookup': row.owner = 'foreign'
            elif change == 'state': row.state = 'unknown'
            elif change == 'task': row.task_id = 'other-task'
            elif change == 'fingerprint': row.fingerprint = 'other'
            elif change == 'snapshot': saved['summary_snapshot_sha256'] = 'other'
            else: saved['summary_input_view_revision'] = 'historical'
            row.receipt_json = json.dumps(saved)
        return original(*args)
    monkeypatch.setattr(c.service, '_bind_layout_revision', changed)
    c.service.run_once(receipt.task_id, 'alice', c.note)
    c.note.generate_from_transcript.assert_not_called()
    assert c.artifacts.get_status(receipt.task_id)['status'] == 'failed'
    assert c.artifacts.get_status(receipt.task_id)['error_code'] == 'summary_preflight_visual_changed'


@pytest.mark.parametrize('value', [None, True, False, 1.0, '1', 2])
def test_corrupt_policy_is_not_treated_as_legacy_absence(case, monkeypatch, value):
    c = case; setup_service(c, monkeypatch); receipt, _ = accept(c)
    from app.db_models import SourceRequestDB
    with c.receipts.sessions() as db:
        row = db.get(SourceRequestDB, ('alice', str(c.body.operation_id)))
        saved = json.loads(row.receipt_json); saved['summary_ocr_layout_policy'] = value
        row.receipt_json = json.dumps(saved)
    prep = Mock(side_effect=AssertionError('policy gate must precede preparation'))
    monkeypatch.setattr('app.services.meeting_video_ocr.prepare_meeting_video_ocr', prep)
    c.service.run_once(receipt.task_id, 'alice', c.note)
    prep.assert_not_called(); c.note.generate_from_transcript.assert_not_called()
    assert c.artifacts.get_status(receipt.task_id)['status'] == 'failed'
    assert c.artifacts.get_status(receipt.task_id)['error_code'] == 'summary_preflight_visual_changed'


def test_receipt_cas_preserves_concurrent_fields_instead_of_overwriting(case, monkeypatch):
    from contextlib import contextmanager
    from sqlalchemy.sql.dml import Update
    from app.db_models import SourceRequestDB
    c = case; setup_service(c, monkeypatch); receipt, _ = accept(c)
    real_sessions = c.receipts.sessions
    original = c.service._bind_layout_revision
    injections = []
    @contextmanager
    def racing_sessions():
        with real_sessions() as db:
            class Proxy:
                def __getattr__(self, name): return getattr(db, name)
                def execute(self, statement, **kwargs):
                    if isinstance(statement, Update):
                        with real_sessions() as other:
                            row = other.get(SourceRequestDB, ('alice', str(c.body.operation_id)))
                            saved = json.loads(row.receipt_json); saved['independent_concurrent_marker'] = 'retained'
                            row.receipt_json = json.dumps(saved)
                        injections.append(True)
                    return db.execute(statement, **kwargs)
            yield Proxy()
    def race(*args):
        c.receipts.sessions = racing_sessions
        try: return original(*args)
        finally: c.receipts.sessions = real_sessions
    monkeypatch.setattr(c.service, '_bind_layout_revision', race)
    c.service.run_once(receipt.task_id, 'alice', c.note)
    assert injections == [True]
    c.note.generate_from_transcript.assert_not_called()
    with real_sessions() as db:
        saved = json.loads(db.get(SourceRequestDB, ('alice', str(c.body.operation_id))).receipt_json)
    assert saved['independent_concurrent_marker'] == 'retained'
    assert 'summary_input_view_revision' not in saved and 'summary_ocr_layout_sha256' not in saved
