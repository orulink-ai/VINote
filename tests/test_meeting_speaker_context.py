from copy import deepcopy
from types import SimpleNamespace

from app.services import meeting_speaker_context as speaker


def context():
    return {'note_key': 'note', 'canonical_task_id': 'canonical', 'evidence_revision': 'a' * 64,
            'confirmation_revision': 2, 'binding_hash': 'b' * 64,
            'speakers': [{'speaker_id': 'speaker_1', 'samples': [{'association': 'segment_speaker'}]},
                         {'speaker_id': 'speaker_2', 'samples': [{'association': 'time_overlap'}]}],
            'speaker_matches': [{'speaker_id': 'speaker_1', 'open_id': 'ou_a', 'name': '陈一'},
                                {'speaker_id': 'speaker_2', 'open_id': 'ou_b', 'name': '李二'}]}


def test_capture_keeps_confirmation_without_using_truncated_ui_samples_as_authority(monkeypatch):
    monkeypatch.setattr(speaker, '_lookup', lambda owner, parent: context())
    frozen = speaker.capture_speaker_context('owner', 'parent')
    assert frozen['matches'] == [{'speaker_id': 'speaker_1', 'name': '陈一'}, {'speaker_id': 'speaker_2', 'name': '李二'}]
    assert 'ou_a' not in str(frozen)


def test_extras_rechecks_scope_and_does_not_mutate_transcript(monkeypatch):
    current = context()
    monkeypatch.setattr(speaker, '_lookup', lambda owner, parent: current)
    frozen = speaker.capture_speaker_context('owner', 'parent')
    transcript = SimpleNamespace(segments=[SimpleNamespace(speaker_id='speaker_1', speaker_label='说话人1', timestamp_estimated=False)])
    before = deepcopy(transcript)
    value = speaker.speaker_extras('owner', 'parent', '保留结论', frozen, transcript)
    assert '陈一' in value and '说话人1' in value and '李二' not in value
    assert transcript == before and value.startswith('保留结论')
    current['confirmation_revision'] += 1
    assert speaker.speaker_extras('owner', 'parent', '保留结论', frozen, transcript) == '保留结论'


def test_legacy_or_wrong_owner_receipt_never_uses_current_mapping(monkeypatch):
    monkeypatch.setattr(speaker, '_lookup', lambda *_: (_ for _ in ()).throw(AssertionError('must not read')))
    transcript = SimpleNamespace(segments=[])
    assert speaker.speaker_extras('owner', 'parent', None, None, transcript) is None
    assert speaker.speaker_extras('other', 'parent', None, {'owner': 'owner'}, transcript) is None


def test_optional_unavailable_connection_preserves_generation(monkeypatch):
    monkeypatch.setattr(speaker, '_lookup', lambda *_: None)
    assert speaker.capture_speaker_context('owner', 'parent') is None


def test_estimated_labels_are_never_attributed(monkeypatch):
    monkeypatch.setattr(speaker, '_lookup', lambda *_: context())
    frozen = speaker.capture_speaker_context('owner', 'parent')
    transcript = SimpleNamespace(segments=[SimpleNamespace(speaker_id='speaker_1', speaker_label='说话人1', timestamp_estimated=True)])
    assert speaker.speaker_extras('owner', 'parent', '原要求', frozen, transcript) == '原要求'


def test_uses_original_raw_segments_instead_of_estimated_wrapper(monkeypatch):
    monkeypatch.setattr(speaker, '_lookup', lambda *_: context())
    frozen = speaker.capture_speaker_context('owner', 'parent')
    raw = {'full_text': '确认方案', 'segments': [{'start': 0, 'end': 2, 'text': '确认方案',
            'speaker_id': 'speaker_1'}], 'metadata': {'timestamp_granularity': 'segment'}}
    transcript = SimpleNamespace(segments=[], metadata={'asr_evidence': raw})
    before = deepcopy(raw)
    assert '陈一' in speaker.speaker_extras('owner', 'parent', None, frozen, transcript)
    assert raw == before
