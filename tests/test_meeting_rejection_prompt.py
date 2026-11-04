import json
import pytest

from app.llm.meeting_final_claim_ledger import REVIEW_PROTOCOL, FinalLedgerError, validate_final_ledger
from tests.test_meeting_final_claim_ledger import draft, review, run


def test_protocol_provides_machine_readable_rejected_row_and_exact_enum():
    assert '"disposition":"rejected"' in REVIEW_PROTOCOL
    assert '"reason_code":"unsupported"' in REVIEW_PROTOCOL
    assert 'exactly one' in REVIEW_PROTOCOL
    assert 'Do not join' in REVIEW_PROTOCOL


def test_rejection_reason_remains_strictly_validated():
    material = draft()
    value = review()
    value['claims'][0].update(disposition='rejected', block_ids=[], reason='No source support',
                              reason_code='unsupported/misread')
    with pytest.raises(FinalLedgerError) as error:
        run(value, material)
    assert error.value.code == 'invalid_rejection'


@pytest.mark.parametrize('presentation', ['comic', 'infographic'])
def test_protocol7_copies_exact_source_rules_when_other_paragraphs_shift(monkeypatch, presentation):
    import app.llm.meeting_final_claim_ledger as ledger
    from app.llm.meeting_single_copy_projection7 import review_protocol7
    source_rules = [line for line in ledger.REVIEW_PROTOCOL.splitlines()
                    if line.startswith(('For asr_span quote', 'Independently review the complete original speech'))]
    assert len(source_rules) == 2
    monkeypatch.setattr(ledger, 'REVIEW_PROTOCOL', ledger.REVIEW_PROTOCOL.replace(
        'For asr_span quote', 'Additional unrelated rule.\nFor asr_span quote', 1))
    result = review_protocol7(presentation)
    for rule in source_rules:
        assert rule in result.splitlines()
