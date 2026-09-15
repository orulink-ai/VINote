from unittest.mock import patch

import pytest

from app.config import settings
from app.llm.openai_llm import _BasePromptLLM
from app.llm.vilab_llm import VILabLLM
from app.models.transcript import TranscriptSegment


class ReviewLLM(_BasePromptLLM):
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def _complete(self, **prompts):
        self.calls.append(prompts)
        return next(self.replies)


def test_meeting_returns_reviewed_content_and_supplies_original_evidence():
    llm = ReviewLLM(["Human performs everything.", "The tool runs the workflow."])
    progress = []
    result = llm.summarize(
        "Meeting", [TranscriptSegment(20, 30, "Ask the tool to run the workflow.")],
        style="meeting", extras="Meeting paused at noon.", progress_callback=progress.append,
    )
    assert result == "The tool runs the workflow."
    review = llm.calls[1]["user_prompt"]
    assert "Ask the tool to run the workflow." in review
    assert "Human performs everything." in review
    assert "Meeting paused at noon." in review
    assert progress


def test_empty_review_does_not_silently_accept_unreviewed_draft():
    llm = ReviewLLM(["An unchecked draft", " "])
    with pytest.raises(RuntimeError, match="事实复核"):
        llm.summarize("Meeting", [TranscriptSegment(0, 1, "hello")], style="meeting")


def test_hierarchical_meeting_reviews_chunks_before_merge_and_final_result():
    llm = ReviewLLM(["draft one", "verified one", "draft two", "verified two",
                     "merged draft", "verified final"])
    segments = [TranscriptSegment(0, 2, "source one"), TranscriptSegment(3, 5, "source two")]
    with patch.object(llm, "_chunk_segments", return_value=[[segments[0]], [segments[1]]]):
        result = llm.summarize("Meeting", segments, style="meeting", summary_mode="accurate")
    assert result == "verified final"
    assert "source one" in llm.calls[1]["user_prompt"]
    assert "source two" not in llm.calls[1]["user_prompt"]
    assert "verified one" in llm.calls[4]["user_prompt"]
    assert "draft one" not in llm.calls[4]["user_prompt"]
    assert "verified two" in llm.calls[5]["user_prompt"]


@pytest.mark.parametrize("available,expected", [(True, "reviewer"), (False, "primary")])
def test_cloud_reviewer_uses_available_preference_without_changing_primary(available, expected):
    llm = VILabLLM("test-user", "primary")
    catalog = [{"id": "reviewer", "modelType": "llm",
                "runtimeStatus": "available" if available else "unavailable"}]
    used = []

    def complete(self, **_):
        used.append(self.model)
        return "reviewed"

    with patch.object(settings, "meeting_review_model", "reviewer"), \
            patch("app.llm.vilab_llm.VILabCloudService.models", return_value=catalog) as models, \
            patch.object(VILabLLM, "_complete", complete):
        assert llm._complete_review(system_prompt="system", user_prompt="evidence") == "reviewed"
        llm._complete_review(system_prompt="system", user_prompt="more evidence")
    assert used == [expected, expected]
    assert llm.model == "primary"
    models.assert_called_once_with("test-user")
