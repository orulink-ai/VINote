import pytest

from app.llm.meeting_presentation import presentation_scope
from app.llm.meeting_review import build_meeting_review_prompts


@pytest.mark.parametrize("depth", ["brief", "concise", "detailed"])
@pytest.mark.parametrize("presentation", ["text", "html", "illustrated"])
def test_review_heading_format_is_consistent_with_content_driven_sections(depth, presentation):
    with presentation_scope(depth, presentation):
        rules = build_meeting_review_prompts(
            source="[ASR:0001] Synthetic source.", draft="{}", extras=None,
            output_language="en",
        )["system_prompt"]
    assert "one # meeting title" in rules
    assert "## headings for substantive topics" in rules
    assert "no forced thematic templates" in rules
    assert "no fixed headings" not in rules
    assert "no fixed sections" not in rules
    assert "Every original draft claim ID must appear exactly once" in rules
    assert "never correct punctuation, repetitions, spelling, spacing or broken grammar" in rules
