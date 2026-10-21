"""Proposed offline regression tests; synthetic sources, no provider execution."""
import copy
import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

import app.llm.meeting_review_draft_view as view_module
from app.llm.meeting_final_claim_ledger import FinalLedgerError
from app.llm.meeting_presentation import presentation_scope
from app.llm.openai_llm import _BasePromptLLM
from app.llm.vilab_llm import VILabLLM
from app.models.transcript import TranscriptSegment
from test_meeting_final_review import SOURCE, case, response
from test_meeting_final_review import finalize
from test_meeting_visual_protocol5_adapter import seven
from tests.test_meeting_summary_regeneration import case as summary_case, accept as accept_summary


def material():
    return {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic constraints'}], 'claims': [
        {'id': 'C1', 'topic_id': 'T1', 'field': 'condition', 'text': 'Keep the amber latch closed.',
         'material': True, 'disposition': 'included', 'evidence': [
             {'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': 'Exact  text?!',
              'start': 0, 'end': 13, 'verification': 'unverified'},
             {'kind': 'ocr_span', 'source_ref': '[FRAME:0001]', 'quote': '原 字  符',
              'verification': 'exact_ocr_span'},
             {'kind': 'frame_observation', 'source_ref': '[FRAME:0002]',
              'observation': 'Untrusted interpretation A.', 'verification': 'model_visual_observation'}]},
        {'id': 'C2', 'topic_id': 'T1', 'field': 'condition', 'text': 'Open only after the fourth bell.',
         'material': False, 'disposition': 'omitted_for_depth', 'reason': 'Synthetic selection',
         'evidence': [{'kind': 'frame_observation', 'source_ref': '[FRAME:9999]',
                       'observation': 'Unverified interpretation B.', 'verification': 'unverified'}]},
    ]}


def test_view_preserves_meaning_identity_disposition_and_valid_spans():
    original = material()
    raw = json.dumps(original, ensure_ascii=False, indent=2)
    viewed = json.loads(view_module.review_draft_input_view(raw))
    assert set(viewed) == {'original_claims_view'}
    expected = copy.deepcopy(original)
    expected.pop('protocol')
    for key in ('quote', 'start', 'end'):
        expected['claims'][0]['evidence'][0].pop(key)
    expected['claims'][0]['evidence'][2].pop('observation')
    expected['claims'][0]['evidence'][2].pop('verification')
    expected['claims'][1]['evidence'][0].pop('observation')
    assert viewed['original_claims_view'] == expected
    assert json.loads(raw) == original
    assert viewed['original_claims_view']['claims'][0]['text'] != viewed['original_claims_view']['claims'][1]['text']
    assert viewed['original_claims_view']['claims'][1]['evidence'][0]['verification'] == 'unverified'
    assert all('observation' not in e for c in viewed['original_claims_view']['claims']
               for e in c['evidence'] if e['kind'] == 'frame_observation')


def test_changed_observation_interpretations_cannot_leak_into_view():
    first, second = material(), material()
    second['claims'][0]['evidence'][2]['observation'] = 'Different untrusted attribution.'
    assert view_module.review_draft_input_view(json.dumps(first)) == view_module.review_draft_input_view(json.dumps(second))


def test_valid_spans_without_image_observations_preserve_exact_input_bytes():
    value = material()
    for claim in value['claims']:
        claim['evidence'] = [e for e in claim['evidence'] if e['kind'] != 'frame_observation']
        for evidence in claim['evidence']:
            if evidence.get('kind') == 'asr_span':
                evidence['verification'] = 'exact_asr_span'
    raw = ' \n' + json.dumps(value, ensure_ascii=False, indent=3) + '\n '
    assert view_module.review_draft_input_view(raw) == raw


@pytest.mark.parametrize('kind,ref', [('asr_span', '[ASR:0001]'), ('ocr_span', '[FRAME:0001]')])
def test_unverified_span_only_uses_location_wrapper_without_echo_or_fake_empty_quote(kind, ref):
    original = material()
    evidence = {'kind': kind, 'source_ref': ref, 'verification': 'unverified',
                'quote': 'Unmatched invented quotation.', 'start': 7, 'end': 36}
    original['claims'] = [{**original['claims'][0], 'evidence': [evidence]}]
    raw = json.dumps(original, ensure_ascii=False)
    actual = json.loads(view_module.review_draft_input_view(raw))
    expected = copy.deepcopy(original)
    expected.pop('protocol')
    expected['claims'][0]['evidence'] = [{'kind': kind, 'source_ref': ref, 'verification': 'unverified'}]
    assert actual == {'original_claims_view': expected}
    assert json.loads(raw) == original
    changed = copy.deepcopy(original)
    changed['claims'][0]['evidence'][0].update(quote='Another unmatched span.', start=31, end=53)
    assert view_module.review_draft_input_view(json.dumps(changed, ensure_ascii=False)) == view_module.review_draft_input_view(raw)


@pytest.mark.parametrize('protocol', [None, True, 2, 4, 5, 6])
def test_view_is_not_an_upgrade_or_a_new_material_parser(protocol):
    value = material()
    value['protocol'] = protocol
    with pytest.raises(FinalLedgerError) as error:
        view_module.review_draft_input_view(json.dumps(value))
    assert error.value.code == 'invalid_draft_protocol'


@pytest.mark.parametrize('observation', [None, '', '  ', 4])
def test_missing_observation_is_not_repaired_with_an_empty_string(observation):
    value = material()
    value['claims'][0]['evidence'][2]['observation'] = observation
    with pytest.raises(FinalLedgerError) as error:
        view_module.review_draft_input_view(json.dumps(value))
    assert error.value.code == 'invalid_draft'


def test_duplicate_json_keys_are_not_silently_discarded():
    with pytest.raises(FinalLedgerError) as error:
        view_module.review_draft_input_view('{"protocol":3,"protocol":3,"claims":[]}')
    assert error.value.code == 'duplicate_json_key'


def test_location_only_image_row_is_not_valid_final_evidence(case):
    original = json.dumps(case.material)
    viewed = json.loads(view_module.review_draft_input_view(original))['original_claims_view']
    value = response(case, 'text')
    value['claims'][0]['evidence'] = viewed['claims'][0]['evidence']
    with pytest.raises(FinalLedgerError) as error:
        finalize(case, value, 'text')
    assert error.value.code == 'invalid_final_evidence'


@pytest.mark.parametrize('presentation', ['text', 'html', 'illustrated', 'comic', 'infographic'])
@pytest.mark.parametrize('depth', ['brief', 'concise', 'detailed'])
def test_actual_adapter_changes_only_review_draft_view_and_keeps_original_for_guard(case, monkeypatch, record_property, presentation, depth):
    c = case
    monkeypatch.setattr('app.services.tracing_service.observation', lambda *a, **k: nullcontext(None))
    monkeypatch.setattr(httpx.Client, 'request', lambda *a, **k: pytest.fail('No network'))
    value = seven(c, presentation) if presentation in {'comic', 'infographic'} else response(c, presentation)
    projector = view_module.review_draft_input_view
    import app.llm.meeting_final_review as host
    guard = host.finalize_final_review

    def capture(project):
        calls, guard_inputs = [], []
        monkeypatch.setattr(view_module, 'review_draft_input_view', project)

        def request(self, owner, method, path, **kwargs):
            assert method == 'POST' and path == '/openai/v1/chat/completions'
            calls.append(copy.deepcopy(kwargs['json']))
            assert len(calls) <= 2
            return {'choices': [{'message': {'content': json.dumps(c.material if len(calls) == 1 else value)}}]}

        def checked(raw, original):
            guard_inputs.append(original)
            return guard(raw, original)

        monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request', request)
        monkeypatch.setattr(host, 'finalize_final_review', checked)
        llm = VILabLLM('synthetic-owner', 'frozen-synthetic-model')
        llm.configure_video_capabilities({'max_images': 64}, image_input_verified=True)
        with presentation_scope(depth, presentation) as state:
            body = llm.summarize('Synthetic', [TranscriptSegment(0, 10, SOURCE)],
                                 style='meeting', video_evidence=c.evidence)
        assert len(calls) == 2 and len(guard_inputs) == 1
        assert state.raw_review == json.dumps(value)
        return calls, body, guard_inputs[0]

    baseline, old_body, original = capture(lambda raw: raw)
    candidate, new_body, guarded_original = capture(projector)
    assert original == guarded_original and json.loads(original)['protocol'] == 3
    assert old_body == new_body
    wire = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    assert wire(baseline[0]) == wire(candidate[0])
    assert baseline[1]['messages'][0] == candidate[1]['messages'][0]
    record_property('draft_request_bytes', len(wire(baseline[0])))
    record_property('baseline_review_request_bytes', len(wire(baseline[1])))
    record_property('candidate_review_request_bytes', len(wire(candidate[1])))
    record_property('calls_per_pipeline', 2)
    projected = projector(original)
    first = candidate[1]['messages'][1]['content'][0]
    assert first['text'].count(projected) == 1
    first['text'] = first['text'].replace(projected, original, 1)
    assert wire(baseline[1]) == wire(candidate[1])


@pytest.mark.parametrize('intermediate,depth', [(False, None), (True, None), (True, 'detailed')])
def test_legacy_and_intermediate_review_do_not_invoke_view(monkeypatch, intermediate, depth):
    monkeypatch.setattr(view_module, 'review_draft_input_view', lambda *a: pytest.fail('No structured view here'))

    class Offline(_BasePromptLLM):
        def _complete_review(self, **prompts):
            return 'Legacy report'

    with presentation_scope(depth, 'text'):
        result = Offline()._review_meeting_note(source=SOURCE, draft='Legacy draft', extras=None,
            output_language='en', intermediate=intermediate)
    assert result == 'Legacy report'


@pytest.mark.parametrize('valid_final_quote', [False, True])
def test_actual_note_pipeline_hides_bad_quote_but_original_guard_still_rejects_echo(
        summary_case, monkeypatch, valid_final_quote):
    from app.services.note_service import NoteService
    import app.llm.meeting_final_review as host
    c = summary_case
    source = c.transcript['full_text']
    invented = 'Invented span cannot be evidence.'
    draft = {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Synthetic topic'}], 'claims': [
        {'id': 'C1', 'topic_id': 'T1', 'field': 'attribute', 'text': source, 'material': True,
         'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': invented,
                       'start': 0, 'end': len(invented), 'verification': 'exact_asr_span'}]}]}
    final = {'protocol': 4, 'blocks': [{'id': 'B1', 'markdown': source}], 'claims': [
        {'id': 'C1', 'field': 'attribute', 'text': source, 'material': True,
         'disposition': 'included', 'block_ids': ['B1'], 'evidence': [
             {'kind': 'asr_span', 'source_ref': '[ASR:0001]',
              'quote': source if valid_final_quote else invented}]}]}
    raw3, raw4 = json.dumps(draft), json.dumps(final)
    calls, original_guard_inputs, errors = [], [], []
    guard = host.finalize_final_review

    def checked(text, original):
        original_guard_inputs.append(original)
        try:
            return guard(text, original)
        except FinalLedgerError as error:
            errors.append(error.code)
            raise

    def request(self, owner, method, path, **kwargs):
        assert owner == 'alice' and method == 'POST' and path == '/openai/v1/chat/completions'
        calls.append(copy.deepcopy(kwargs['json']))
        assert len(calls) <= 2, 'No repair call'
        if len(calls) == 2:
            assert invented not in json.dumps(calls[-1])
            assert 'unverified' in json.dumps(calls[-1])
            assert source in json.dumps(calls[-1])
        return {'choices': [{'message': {'content': raw3 if len(calls) == 1 else raw4}}]}

    monkeypatch.setattr(host, 'finalize_final_review', checked)
    monkeypatch.setattr('app.services.tracing_service.observation', lambda *a, **k: nullcontext(None))
    monkeypatch.setattr(httpx.Client, 'request', lambda *a, **k: pytest.fail('No network'))
    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request', request)
    runner = object.__new__(NoteService)
    runner.artifact_service = c.artifacts
    runner.llm_service = SimpleNamespace(create_summarizer=Mock(
        return_value=VILabLLM('alice', c.body.model_name)))
    runner.transcription_service = SimpleNamespace(transcribe=Mock(side_effect=AssertionError('No ASR')))
    receipt, _ = accept_summary(c, c.body.model_copy(update={'content_depth': 'detailed', 'presentation': 'text'}))
    folder = c.artifacts.find_task_dir(receipt.task_id)
    transcript_before = (folder / 'transcript.json').read_bytes()
    c.service.run_once(receipt.task_id, 'alice', runner)
    assert len(calls) == 2 and len(original_guard_inputs) == 1
    guarded = json.loads(original_guard_inputs[0])
    assert guarded['claims'][0]['evidence'][0] == {
        **draft['claims'][0]['evidence'][0], 'verification': 'unverified'}
    assert json.loads((folder / 'meeting_working_draft.json').read_bytes())['text'] == raw3
    assert json.loads((folder / 'meeting_fact_review.json').read_bytes())['raw_response'] == raw4
    assert (folder / 'transcript.json').read_bytes() == transcript_before
    status = c.artifacts.get_status(receipt.task_id)
    if valid_final_quote:
        assert errors == [] and status['status'] == 'success'
        assert json.loads((folder / 'result.json').read_bytes())['markdown'] == source
    else:
        assert errors == ['invalid_final_evidence'] and status['status'] == 'failed'
        assert status['retryable'] is False and not (folder / 'result.json').exists()
    runner.transcription_service.transcribe.assert_not_called()


@pytest.mark.parametrize('valid_final_quote', [False, True])
def test_actual_adapter_host_unverified_ocr_quote_hidden_then_revalidated(case, monkeypatch, valid_final_quote):
    import app.llm.meeting_final_review as host
    c = case
    c.evidence.frames[0].ocr_text, c.evidence.frames[0].ocr_status = SOURCE, 'recognized'
    invented = 'Invented OCR quotation.'
    draft = copy.deepcopy(c.material)
    draft['claims'][0]['evidence'] = [{'kind': 'ocr_span', 'source_ref': '[FRAME:0001]',
                                     'quote': invented, 'verification': 'exact_ocr_span'}]
    final = response(c, 'text')
    final['claims'][0]['evidence'] = [{'kind': 'ocr_span', 'source_ref': '[FRAME:0001]',
                                     'quote': SOURCE if valid_final_quote else invented}]
    raw3, raw4 = json.dumps(draft), json.dumps(final)
    calls, original_inputs = [], []
    guard = host.finalize_final_review

    def checked(text, original):
        original_inputs.append(original)
        return guard(text, original)

    def request(self, owner, method, path, **kwargs):
        calls.append(copy.deepcopy(kwargs['json']))
        assert len(calls) <= 2
        if len(calls) == 2:
            assert invented not in json.dumps(calls[-1])
            assert 'unverified' in json.dumps(calls[-1])
        return {'choices': [{'message': {'content': raw3 if len(calls) == 1 else raw4}}]}

    monkeypatch.setattr(host, 'finalize_final_review', checked)
    monkeypatch.setattr('app.services.tracing_service.observation', lambda *a, **k: nullcontext(None))
    monkeypatch.setattr(httpx.Client, 'request', lambda *a, **k: pytest.fail('No network'))
    monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request', request)
    llm = VILabLLM('synthetic-owner', 'frozen-synthetic-model')
    llm.configure_video_capabilities({'max_images': 64}, image_input_verified=True)
    with presentation_scope('detailed', 'text') as state:
        if valid_final_quote:
            assert llm.summarize('Synthetic', [TranscriptSegment(0, 10, SOURCE)],
                                 style='meeting', video_evidence=c.evidence) == SOURCE
        else:
            with pytest.raises(FinalLedgerError) as error:
                llm.summarize('Synthetic', [TranscriptSegment(0, 10, SOURCE)],
                              style='meeting', video_evidence=c.evidence)
            assert error.value.code == 'invalid_final_evidence'
        assert state.raw_review == raw4
    assert len(calls) == 2 and len(original_inputs) == 1
    assert json.loads(original_inputs[0])['claims'][0]['evidence'][0]['quote'] == invented
    assert json.loads(original_inputs[0])['claims'][0]['evidence'][0]['verification'] == 'unverified'
