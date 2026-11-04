from app.llm.meeting_fact_protocol import DRAFT_PROTOCOL


def test_draft_prompt_requires_complete_evidence_key_value_pairs():
    assert 'Every evidence object must contain complete key-value pairs' in DRAFT_PROTOCOL
    assert '"source_ref":"[ASR:0001]"' in DRAFT_PROTOCOL
    assert 'never output a key without a colon and value' in DRAFT_PROTOCOL


def test_draft_prompt_restricts_evidence_kind_to_protocol_values():
    assert 'only asr_span, ocr_span or frame_observation' in DRAFT_PROTOCOL
