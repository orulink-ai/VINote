"""The two model requests must agree on their actual response envelope."""
import pytest

from app.llm.meeting_draft import build_meeting_draft_prompts
from app.llm.meeting_review import build_meeting_review_prompts
from app.llm.meeting_presentation import presentation_scope
from app.llm.prompts import build_system_prompt


@pytest.mark.parametrize('presentation', ['text', 'html', 'illustrated', 'comic', 'infographic'])
def test_structured_stages_do_not_inherit_markdown_only_outer_response(presentation):
    source = '[ASR:0001] Synthetic source: verify the interlock before opening.'
    with presentation_scope('concise', presentation):
        draft = build_meeting_draft_prompts(title='Synthetic', source=source, extras=None, output_language='en')
        review = build_meeting_review_prompts(source=source, draft='Synthetic fallible draft', extras=None, output_language='en')
    for prompts in [draft, review]:
        assert source in prompts['user_prompt']
        assert 'exactly one JSON object' in prompts['system_prompt']
        assert 'Return only the final Markdown content' not in prompts['system_prompt']
        assert 'Return only the report, without' not in prompts['system_prompt']
    assert 'FINAL CLAIM LEDGER PROTOCOL 4' in review['system_prompt']
    assert 'Define and account for each proposition together' in review['system_prompt']
    assert 'protocol-3 blocks/audit' not in review['system_prompt']
    assert 'This core ledger has no' not in review['system_prompt']


def test_legacy_and_intermediate_requests_keep_the_original_markdown_envelope():
    draft = build_meeting_draft_prompts(title='Synthetic', source='Original', extras=None, output_language='zh-CN')
    with presentation_scope('detailed', 'text'):
        review = build_meeting_review_prompts(source='Original', draft='Draft', extras=None,
                                             output_language='zh-CN', intermediate=True)
    for prompts in [draft, review]:
        assert prompts['system_prompt'].startswith(build_system_prompt('zh-CN'))
        assert 'exactly one JSON object' not in prompts['system_prompt']
        assert 'trace its tail continuously to its own arrowhead' not in prompts['system_prompt']
        assert 'A listing title is not the configuration of its selected offer' not in prompts['system_prompt']


@pytest.mark.parametrize('language', ['zh-CN', 'en'])
@pytest.mark.parametrize('depth', ['brief', 'concise', 'detailed'])
@pytest.mark.parametrize('presentation', ['text', 'html', 'illustrated', 'comic', 'infographic'])
def test_materiality_contract_is_specific_to_the_actual_stage(language, depth, presentation):
    source = '[ASR:0001] Full synthetic source\nKeep punctuation,  2 spaces, and material_reason as source data.'
    with presentation_scope(depth, presentation):
        draft = build_meeting_draft_prompts(title='Synthetic', source=source, extras=None,
                                            output_language=language)
        review = build_meeting_review_prompts(source=source, draft='Fallible original claims',
                                              extras=None, output_language=language)
    for prompts in (draft, review):
        assert source in prompts['user_prompt']
        for obsolete in ('material_reason', 'fact_ids', 'included audit passage'):
            assert obsolete not in prompts['system_prompt']
        assert 'materiality is not certainty' in prompts['system_prompt']
        assert 'No source window or frame is required to yield a business fact' in prompts['system_prompt']
    assert 'Classify each unique draft claim' in draft['system_prompt']
    assert 'Do not reclassify original.material' not in draft['system_prompt']
    assert 'Classify each unique draft claim' not in review['system_prompt']
    assert "Preserve every original claim's id, field and material exactly as frozen in the draft" in review['system_prompt']
    assert 'Do not reclassify original.material' in review['system_prompt']
    assert 'Classify material only for genuinely new source-supported claim IDs' in review['system_prompt']
    assert 'specific valid source-grounded reason' in review['system_prompt']
    assert review['user_prompt'].index('Fallible original claims') < review['user_prompt'].index(source)
    assert review['user_prompt'].count(source) == 1
    from app.llm.meeting_presentation import final_depth_selection
    assert final_depth_selection(depth) in review['system_prompt']
    assert final_depth_selection(depth) not in draft['system_prompt']


@pytest.mark.parametrize('depth', ['brief', 'concise', 'detailed'])
@pytest.mark.parametrize('presentation', ['text', 'html', 'illustrated', 'comic', 'infographic'])
def test_source_fidelity_replacements_reach_both_stages_without_rewriting_source(depth, presentation):
    # These are untrusted synthetic source distinctions, not expected model answers.
    source = ('[ASR:0001] Keep Q0 distinct from QO and 4*7 distinct from 4–7.\n'
              '[ASR:0002] Continue the same journey after arrival; do not invent another trip.\n'
              '[ASR:0003] The displayed checkbox is a document mark, not completion proof.\n'
              '[ASR:0004] The family title, selected option and conditional price are separate.\n'
              '[ASR:0005] OCR disagrees with the image; independent speech may also disagree.\n'
              '[ASR:0006] A shared junction does not give every node an outgoing arrow.\n'
              '[ASR:0007] Keep  repeated spacing and punctuation?! unchanged in a quote.')
    frozen_draft = 'Untrusted prior interpretation; preserve original id/field/material.'
    with presentation_scope(depth, presentation):
        draft = build_meeting_draft_prompts(title='Synthetic', source=source, extras=None,
                                           output_language='en')
        review = build_meeting_review_prompts(source=source, draft=frozen_draft, extras=None,
                                              output_language='en')
    shared_checks = (
        'recheck exact characters, decimal/grouping signs and operators',
        'An explicitly continuing arrangement remains one event across its stages',
        'its own legible checked or unchecked mark as document state, not verified real-world completion',
        'trace its tail continuously to its own arrowhead through any branch junction',
        'An arrowhead entering a node does not establish an outgoing edge from that node',
        'A listing title is not the configuration of its selected offer',
        'current, crossed-out reference, conditional discount and unavailable prices',
        'OCR and ASR are fallible recognition',
        'clear supplied images of the same visible content',
        'different OCR readings alone do not establish a source conflict',
        'A frame_observation describes that inspection, never relabelled recognition text',
        'Keep genuinely different source values and independent speech/image disagreements',
        'Unavailable or unreadable images resolve nothing',
        'Evidence quotes remain unchanged',
        'Retain legible specification alternatives and combined requirements',
        'Do not present a newly calculated time, budget or timetable as a stated arrangement',
    )
    for prompts in (draft, review):
        assert prompts['user_prompt'].count(source) == 1
        for instruction in shared_checks:
            assert prompts['system_prompt'].count(instruction) == 1
        for replaced in ('For every reported number, recheck value',
                         "Inspect each branch's arrowhead independently",
                         'A product title may cover several variants',
                         'OCR and ASR are recognition results',
                         'Compare event predicates before and after review'):
            assert replaced not in prompts['system_prompt']
    assert frozen_draft in review['user_prompt']
    assert 'Preserve each original ID, field and boolean material flag' in review['system_prompt']
    assert 'Each row requires id/field/text/material/disposition/block_ids/evidence' in review['system_prompt']
    assert 'never correct punctuation, repetitions, spelling, spacing or broken grammar inside it' in review['system_prompt']
    node_rule = 'Select self-contained unchanged excerpts naming objects and essential attributes'
    assert node_rule not in draft['system_prompt']
    assert review['system_prompt'].count(node_rule) == (1 if presentation == 'infographic' else 0)
    if presentation == 'infographic':
        for instruction in ('Never split an object and its values across independent nodes',
                            'omit unsuitable excerpts rather than expand prose',
                            'unchanged contiguous substrings', 'Cards/comparison have no edges',
                            'Do not manufacture relations to fill a graph'):
            assert instruction in review['system_prompt']
