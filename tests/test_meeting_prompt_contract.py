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
