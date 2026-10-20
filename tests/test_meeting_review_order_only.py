"""Claims-first is a prompt order, never a new schema or acceptance gate."""
import copy
import json
from contextlib import nullcontext

import httpx
import pytest

import app.llm.meeting_final_review as host
from app.llm.meeting_draft import build_meeting_draft_prompts
from app.llm.meeting_final_claim_ledger import FinalLedgerError, REVIEW_PROTOCOL
from app.llm.meeting_presentation import presentation_scope
from app.llm.meeting_review import build_meeting_review_prompts
from app.llm.vilab_llm import VILabLLM
from app.models.transcript import TranscriptSegment
from test_meeting_final_review import SOURCE, case, finalize, response
from test_meeting_visual_protocol5_adapter import five, six


OLD_ORDER = 'Write the report once in ordered blocks.'
NEW_ORDER = ('Complete claims before blocks; their block_ids reference the report blocks that follow. '
             'Then write the report once in ordered blocks.')


def old_rules():
    lines = REVIEW_PROTOCOL.splitlines()
    example = json.loads(lines[1].removesuffix('.'))
    lines[1] = json.dumps({key: example[key] for key in ('protocol', 'blocks', 'claims')},
                         ensure_ascii=False, separators=(',', ':')) + '.'
    assert REVIEW_PROTOCOL.count(NEW_ORDER) == 1
    return '\n'.join(lines).replace(NEW_ORDER, OLD_ORDER)


def assert_only_order_changed(before, after):
    old_lines, new_lines = before.splitlines(), after.splitlines()
    index = next(i + 1 for i, line in enumerate(old_lines)
                 if 'FINAL CLAIM LEDGER PROTOCOL ' in line)
    old_example = json.loads(old_lines[index].removesuffix('.'))
    new_example = json.loads(new_lines[index].removesuffix('.'))
    assert old_example == new_example  # Every schema value and nested array is unchanged.
    assert list(old_example)[:3] == ['protocol', 'blocks', 'claims']
    assert list(new_example)[:3] == ['protocol', 'claims', 'blocks']
    assert list(old_example)[3:] == list(new_example)[3:]
    old_lines[index] = new_lines[index]
    assert '\n'.join(old_lines).replace(OLD_ORDER, NEW_ORDER, 1) == after


@pytest.mark.parametrize('presentation,protocol', [
    ('text', 4), ('html', 4), ('illustrated', 4),
    ('comic', 4), ('infographic', 4), ('comic', 5), ('infographic', 5),
    ('comic', 6), ('infographic', 6),
])
def test_all_explicit_factories_change_only_example_order_and_existing_sentence(monkeypatch, presentation, protocol):
    current = host.review_protocol(presentation, protocol=protocol)
    monkeypatch.setattr(host, 'REVIEW_PROTOCOL', old_rules())
    previous = host.review_protocol(presentation, protocol=protocol)
    assert_only_order_changed(previous, current)


@pytest.mark.parametrize('structured', [False, True])
@pytest.mark.parametrize('intermediate', [False, True])
def test_draft_and_legacy_or_intermediate_review_bytes_are_unchanged(monkeypatch, structured, intermediate):
    def prompts():
        with presentation_scope('concise' if structured else None, 'text'):
            return (
                build_meeting_draft_prompts(title='Synthetic', source=SOURCE, extras=None, output_language='en'),
                build_meeting_review_prompts(source=SOURCE, draft='Fallible fixture', extras=None,
                                             output_language='en', intermediate=intermediate),
            )
    current = prompts()
    monkeypatch.setattr(host, 'REVIEW_PROTOCOL', old_rules())
    previous = prompts()
    assert previous[0] == current[0]
    if not structured or intermediate:
        assert previous[1] == current[1]
    else:
        assert previous[1]['user_prompt'] == current[1]['user_prompt']
        assert_only_order_changed(previous[1]['system_prompt'], current[1]['system_prompt'])


@pytest.mark.parametrize('presentation', ['text', 'html', 'illustrated', 'comic', 'infographic'])
def test_actual_adapter_wire_changes_only_second_system_order(case, monkeypatch, presentation):
    c = case
    monkeypatch.setattr('app.services.tracing_service.observation', lambda *a, **k: nullcontext(None))
    monkeypatch.setattr(httpx.Client, 'request', lambda *a, **k: pytest.fail('No network'))
    value = six(c, presentation) if presentation in {'comic', 'infographic'} else response(c, presentation)

    def capture(rules):
        calls = []
        monkeypatch.setattr(host, 'REVIEW_PROTOCOL', rules)

        def request(self, owner, method, path, **kwargs):
            calls.append(copy.deepcopy(kwargs['json']))
            assert len(calls) <= 2
            return {'choices': [{'message': {'content': json.dumps(c.material if len(calls) == 1 else value)}}]}

        monkeypatch.setattr('app.llm.vilab_llm.VILabCloudService.request', request)
        llm = VILabLLM('synthetic-owner', 'frozen-synthetic-model')
        llm.configure_video_capabilities({'max_images': 64}, image_input_verified=True)
        with presentation_scope('concise', presentation):
            body = llm.summarize('Synthetic', [TranscriptSegment(0, 10, SOURCE)],
                                 style='meeting', video_evidence=c.evidence)
        assert len(calls) == 2
        return calls, body

    previous, old_body = capture(old_rules())
    current, new_body = capture(REVIEW_PROTOCOL)
    assert old_body == new_body
    assert previous[0] == current[0]  # Complete draft request, including all actual image bytes.
    wire_bytes = lambda payload: json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    assert wire_bytes(previous[0]) == wire_bytes(current[0])
    old_system = previous[1]['messages'][0]['content']
    new_system = current[1]['messages'][0]['content']
    assert_only_order_changed(old_system, new_system)
    previous[1]['messages'][0]['content'] = new_system
    assert previous[1] == current[1]  # Complete source, OCR, images, model and transport options.
    assert wire_bytes(previous[1]) == wire_bytes(current[1])


@pytest.mark.parametrize('presentation,protocol', [
    ('text', 4), ('html', 4), ('illustrated', 4), ('comic', 4), ('infographic', 4),
    ('comic', 5), ('infographic', 5), ('comic', 6), ('infographic', 6),
])
@pytest.mark.parametrize('invalid_quote', [False, True])
def test_both_member_orders_keep_body_visual_and_strict_quote_acceptance(case, presentation, protocol, invalid_quote):
    value = (six(case, presentation) if protocol == 6 else five(case, presentation)
             if protocol == 5 else response(case, presentation))
    if invalid_quote:
        value['claims'][0]['evidence'][0]['quote'] = 'Not present in the original source.'
    outputs = []
    for keys in [('protocol', 'blocks', 'claims'), ('protocol', 'claims', 'blocks')]:
        ordered = {key: copy.deepcopy(value[key]) for key in keys}
        ordered.update({key: copy.deepcopy(item) for key, item in value.items() if key not in keys})
        if invalid_quote:
            with pytest.raises(FinalLedgerError) as error:
                finalize(case, ordered, presentation)
            assert error.value.code == 'invalid_final_evidence'
        else:
            body, state = finalize(case, ordered, presentation)
            assert state.raw_review == json.dumps(ordered)
            outputs.append((body, state.visual_review, state.figures))
    if not invalid_quote:
        assert outputs[0] == outputs[1]
