import json

import pytest

from app.llm.meeting_presentation import presentation_scope
from app.llm.meeting_review import build_meeting_review_prompts


@pytest.mark.parametrize("wrapped", [False, True])
def test_review_accounts_for_original_claims_in_both_draft_shapes(wrapped):
    # Matches the protocol-3 text saved inside meeting_working_draft.json.
    original = {"protocol": 3, "topics": [], "claims": [
        {"id": "C1", "field": "condition", "text": "Example", "material": True, "evidence": []},
        {"id": "C2", "field": "condition", "text": "Another", "material": True, "evidence": []},
    ]}
    draft = json.dumps({"original_claims_view": original} if wrapped else original)
    source = "[ASR:0001] Unique synthetic source marker."
    with presentation_scope("detailed", "text"):
        prompts = build_meeting_review_prompts(
            source=source, draft=draft, extras=None, output_language="en"
        )
    user = prompts["user_prompt"]
    assert "Original claim count: 2." in user
    assert 'Original claim IDs: ["C1", "C2"]' in user
    assert ("original_claims_view.claims" if wrapped else "claims") in user
    assert user.count(source) == 1
    assert "never permits skipping original claim IDs" in prompts["system_prompt"]
    assert "For nonempty source, blocks must be nonempty" in prompts["system_prompt"]


@pytest.mark.parametrize("draft", [
    "Synthetic fallible draft",
    '{"protocol":3,',
    '{"protocol":2,"claims":[{"id":"C1"}]}',
    '{"protocol":3,"claims":[{}]}',
    '{"protocol":3,"claims":[{"id":"C1"},{"id":"C1"}]}',
])
def test_other_drafts_are_preserved_without_an_invented_id_list(draft):
    with presentation_scope("detailed", "text"):
        prompt = build_meeting_review_prompts(
            source="Unique source", draft=draft, extras=None, output_language="en"
        )["user_prompt"]
    assert draft in prompt
    assert "Original claim IDs:" not in prompt
    assert prompt.count("Unique source") == 1
