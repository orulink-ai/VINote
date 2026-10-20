"""Proposed offline regression tests; synthetic sources, no provider execution."""
import copy
import json
from contextlib import nullcontext

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
from test_meeting_visual_protocol5_adapter import six


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


def test_view_preserves_meaning_identity_disposition_and_non_image_evidence():
    original = material()
    raw = json.dumps(original, ensure_ascii=False, indent=2)
    viewed = json.loads(view_module.review_draft_input_view(raw))
    assert set(viewed) == {'original_claims_view'}
    expected = copy.deepcopy(original)
    expected.pop('protocol')
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


def test_no_image_observations_preserves_exact_input_bytes():
    value = material()
    for claim in value['claims']:
        claim['evidence'] = [e for e in claim['evidence'] if e['kind'] != 'frame_observation']
    raw = ' \n' + json.dumps(value, ensure_ascii=False, indent=3) + '\n '
    assert view_module.review_draft_input_view(raw) == raw


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
    value = six(c, presentation) if presentation in {'comic', 'infographic'} else response(c, presentation)
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
