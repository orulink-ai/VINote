import json

import pytest

from app.llm.meeting_final_claim_ledger import FinalLedgerError
from app.llm.meeting_presentation import presentation_scope
from app.llm.source_references import bind_source_references
from app.models.transcript import TranscriptSegment
from tests.test_meeting_empty_review_retry import Reviewer, SOURCE, EMPTY, EMPTY_CLAIMS, VALID, run


@pytest.mark.parametrize("first,second,count", [
    (EMPTY, EMPTY, 2), (EMPTY_CLAIMS, EMPTY_CLAIMS, 2),
    ("invalid_evidence", None, 1), (EMPTY, "invalid_evidence", 2),
])
def test_whole_review_never_dispatches_batches(first, second, count):
    invalid = json.loads(VALID)
    invalid["claims"][0]["evidence"][0]["quote"] = "not in source"
    responses = [json.dumps(invalid) if item == "invalid_evidence" else item
                 for item in (first, second) if item is not None] + [VALID]
    llm = Reviewer(responses)
    with bind_source_references([TranscriptSegment(0, 1, SOURCE)]), presentation_scope("detailed", "text"):
        with pytest.raises(FinalLedgerError):
            run(llm)
    assert len(llm.calls) == count
    if count == 2:
        assert llm.calls[0]["user_prompt"] == llm.calls[1]["user_prompt"]
    assert all("BATCH REVIEW" not in call["system_prompt"] for call in llm.calls)
