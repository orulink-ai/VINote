"""Presentation is deterministic; these tests never call providers."""
import pytest
from pydantic import ValidationError

from app.services.meeting_summary_regeneration import SummaryConfirmation


def test_confirmation_rejects_unknown_depth_and_presentation():
    from uuid import uuid4
    base = dict(operation_id=uuid4(), confirmed=True, context_revision='a' * 64,
                source_version='b' * 64, model_name='selected')
    for field, value in [('content_depth', 'auto'), ('presentation', 'slideshow')]:
        with pytest.raises(ValidationError):
            SummaryConfirmation(**base, **{field: value})


def test_depth_only_changes_final_review_not_evidence_preservation():
    from app.llm.meeting_presentation import presentation_scope, depth_instructions
    from app.llm.meeting_review import build_meeting_review_prompts
    from app.llm.meeting_draft import build_meeting_draft_prompts
    with presentation_scope('brief'):
        review = build_meeting_review_prompts(source='all source', draft='working facts',
                                             extras=None, output_language='en')
        draft = build_meeting_draft_prompts(title='title', source='all source',
                                            extras=None, output_language='en')
    # Structured reports put Markdown in blocks rather than a report field.
    assert depth_instructions('brief').replace('The report field contains Markdown facts only;',
        'Report blocks[].markdown contain Markdown facts only;') in review['system_prompt']
    assert depth_instructions('brief') not in draft['system_prompt']
    assert depth_instructions('brief') not in build_meeting_review_prompts(
        source='all source', draft='facts', extras=None, output_language='en')['system_prompt']
    assert 'all source' in review['user_prompt'] and 'all source' in draft['user_prompt']


def test_presentation_availability_never_invents_generation_capability():
    from app.llm.meeting_presentation import presentation_availability
    options = presentation_availability(has_visuals=False)
    assert all(options[key]['available'] for key in ('text', 'html', 'infographic'))
    assert all(options[key]['available'] is False for key in ('illustrated', 'comic'))
    assert presentation_availability(has_visuals=True)['illustrated']['available']
    assert presentation_availability(has_visuals=True)['comic']['available']
