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
