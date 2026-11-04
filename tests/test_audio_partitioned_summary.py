from app.llm.meeting_source_bundle import SourceBundle, SourceSlot, SourcePrompt, SourceWindow, chronological_content
from app.llm.meeting_source_reads import split_source_reads
from app.services.note_service import should_partition_audio_summary
from app.models.transcript import TranscriptSegment


def test_audio_partitions_preserve_every_original_reference():
    windows = tuple(SourceWindow(f'[ASR:{i + 1:04d}]', i * 10, i * 10 + 9, f'utterance {i}') for i in range(3))
    bundle = SourceBundle(windows, 'source', lambda: None)
    prompt = SourcePrompt(SourceSlot('header', bundle, 'footer'))
    content = chronological_content(prompt, prepare_audio=True)
    reads = split_source_reads(content)
    assert [part.allowed_refs for part in reads] == [frozenset({f'[ASR:{i + 1:04d}]'}) for i in range(3)]
    for part in reads:
        part.validate()
        assert len(part.content) == 3


def test_long_audio_meetings_keep_whole_transcript_generation():
    segments = [TranscriptSegment(i * 1200, i * 1200 + 1199, 'words') for i in range(3)]
    assert not should_partition_audio_summary(segments, style='meeting', depth='concise', presentation='text', mode='default', video=None)
    assert not should_partition_audio_summary(segments[:1], style='meeting', depth='concise', presentation='text', mode='default', video=None)
    assert not should_partition_audio_summary(segments, style='meeting', depth='concise', presentation='text', mode='default', video=object())
    assert not should_partition_audio_summary(segments, style='meeting', depth='concise', presentation='text', mode='accurate', video=None)
