import pytest

from app.services.meeting_evidence import original_asr_evidence


def test_nested_estimated_wrappers_keep_original_session_windows():
    raw = {'full_text': '同一发言', 'segments': [{'start': 120, 'end': 180, 'text': '同一发言'}],
           'metadata': {'timestamp_granularity': 'session'}}
    estimated = {'full_text': '同一发言', 'segments': [{'start': 90, 'end': 95, 'text': '同一发言'}],
                 'metadata': {'asr_evidence': raw}}
    wrapper = {**estimated, 'metadata': {'asr_evidence': estimated}}
    assert original_asr_evidence(wrapper) is raw
    assert original_asr_evidence(wrapper)['segments'][0]['start'] == 120


def test_different_transcript_or_cyclic_evidence_fails_closed():
    raw = {'full_text': '原文', 'segments': [], 'metadata': {}}
    wrapper = {'full_text': '另一份会议', 'segments': [], 'metadata': {'asr_evidence': raw}}
    with pytest.raises(ValueError, match='不一致'):
        original_asr_evidence(wrapper)
    raw['metadata']['asr_evidence'] = raw
    with pytest.raises(ValueError):
        original_asr_evidence(raw)
