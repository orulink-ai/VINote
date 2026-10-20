"""Synthetic media only: full-timeline selection and honest evidence transport."""
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from app.models.transcript import TranscriptSegment
from app.services.video_evidence_service import (
    VideoEvidenceService, VideoEvidenceError, VideoEvidence, VideoFrameEvidence,
)


def synthetic_scan(count, edits=None):
    edits = edits or {}
    pixels = bytearray(160 * 90)
    for second in range(count):
        if second in edits:
            start, length, value = edits[second]
            pixels[start:start + length] = bytes([value]) * length
        yield float(second), bytes(pixels)


def configure_local(monkeypatch, tmp_path, scan, duration=120):
    source = tmp_path / 'original.mp4'
    source.write_bytes(b'retained-original')
    service = VideoEvidenceService(max_frames=12, ocr=Mock(return_value='visible text'))
    monkeypatch.setattr(service, '_probe_duration', lambda _: duration)
    monkeypatch.setattr(service, '_scan', lambda *a: iter(scan))
    extracted = []

    def extract(source, timestamp, destination):
        extracted.append(timestamp)
        # Different synthetic frames; never meeting data.
        Image.new('RGB', (64, 36), (int(timestamp) % 255, 0, 0)).save(destination)
    monkeypatch.setattr(service, '_extract_frame', extract)
    return service, source, extracted


def test_scan_covers_beginning_middle_tail_and_detects_small_whiteboard_edits(monkeypatch, tmp_path):
    service, source, extracted = configure_local(monkeypatch, tmp_path,
        list(synthetic_scan(120, {17: (100, 80, 255), 85: (900, 150, 180)})))
    evidence = service.collect(local_video_path=source, task_dir=tmp_path / 'task',
        transcript_segments=[TranscriptSegment(84, 88, 'A proposal', speaker_id='speaker_1')],
        speaker_evidence=[{'start': 84, 'end': 86, 'speaker_id': 'speaker_2'}])
    assert extracted[0] == 0
    assert max(t for frame in evidence.frames for t in frame.sample_offsets) >= 119
    assert 17 in extracted and 85 in extracted
    assert len(extracted) <= 12
    assert evidence.scan_complete and evidence.scanned_samples == 120
    frame = next(frame for frame in evidence.frames if frame.timestamp == 85)
    assert 'text_or_detail_change' in frame.reasons
    assert frame.speech_indices == [0] and frame.speaker_ids == ['speaker_2']
    prompt = evidence.text_material()
    assert 'A proposal' not in prompt  # Do not duplicate or mutate full speech source.
    assert 'temporal overlap does not establish' in prompt
    assert source.read_bytes() == b'retained-original'


def test_static_video_deduplicates_but_keeps_timeline_occurrences(monkeypatch, tmp_path):
    service, source, extracted = configure_local(monkeypatch, tmp_path, list(synthetic_scan(120)))
    evidence = service.collect(local_video_path=source, task_dir=tmp_path / 'task', transcript_segments=[])
    assert len(evidence.frames) == 1
    assert evidence.frames[0].sample_offsets[0] == 0
    assert evidence.frames[0].sample_offsets[-1] >= 119
    assert len(extracted) == 1


def test_short_or_truncated_scan_is_not_full_coverage(monkeypatch, tmp_path):
    service, source, _ = configure_local(monkeypatch, tmp_path, list(synthetic_scan(10)))
    with pytest.raises(VideoEvidenceError, match='覆盖'):
        service.collect(local_video_path=source, task_dir=tmp_path / 'task', transcript_segments=[])
    assert not (tmp_path / 'task' / 'video_evidence.json').exists()


def test_source_and_output_separation_and_network_input_rejected_before_subprocess(tmp_path):
    service = VideoEvidenceService()
    with pytest.raises(VideoEvidenceError):
        service.collect(local_video_path=Path('https://example.org/video.mp4'), task_dir=tmp_path,
                        transcript_segments=[])
    source = tmp_path / 'original.mp4'
    source.write_bytes(b'original')
    with pytest.raises(VideoEvidenceError):
        service.collect(local_video_path=source, task_dir=source, transcript_segments=[])
    assert source.read_bytes() == b'original'


def test_unavailable_ocr_never_becomes_empty_success_or_fake_visual_text(monkeypatch, tmp_path):
    service, source, _ = configure_local(monkeypatch, tmp_path, list(synthetic_scan(1)), duration=1)
    service.ocr = None
    monkeypatch.setattr(service, '_ocr_frame', lambda _: (None, 'unavailable'))
    evidence = service.collect(local_video_path=source, task_dir=tmp_path / 'task', transcript_segments=[])
    assert evidence.frames[0].ocr_status == 'unavailable'
    with pytest.raises(VideoEvidenceError, match='图片|文字'):
        evidence.user_content('speech source', capabilities={})
    content = evidence.user_content('speech source', capabilities={'vision': {'status': 'supported'}})
    assert any(block['type'] == 'image_url' for block in content)
    assert 'not supplied' not in str(content)


def test_capability_budget_rejection_is_not_silent_image_truncation(tmp_path):
    frames = []
    for index in range(3):
        image = tmp_path / f'{index}.jpg'
        Image.new('RGB', (12, 12)).save(image)
        frames.append(VideoFrameEvidence(float(index), image, ['timeline'], [float(index)]))
    evidence = VideoEvidence(3, frames, scanned_samples=3, scan_complete=True)
    with pytest.raises(VideoEvidenceError, match='图片'):
        evidence.user_content('source', capabilities={'vision': True, 'max_images': 2})
    # A model name alone never grants vision.
    with pytest.raises(VideoEvidenceError):
        evidence.user_content('source', capabilities={'model': 'gpt-6-luna'})


def test_frame_extraction_failure_does_not_shift_timestamps(monkeypatch, tmp_path):
    service, source, _ = configure_local(monkeypatch, tmp_path,
        list(synthetic_scan(120, {30: (0, 14400, 255)})))
    monkeypatch.setattr(service, '_extract_frame', Mock(side_effect=VideoEvidenceError('frame failed')))
    with pytest.raises(VideoEvidenceError):
        service.collect(local_video_path=source, task_dir=tmp_path / 'task', transcript_segments=[])
    assert not (tmp_path / 'task' / 'video_evidence.json').exists()


def test_slow_incremental_changes_accumulate_before_selection(monkeypatch, tmp_path):
    edits = {second: (second * 10, 10, 255) for second in range(1, 120)}
    service, source, _ = configure_local(monkeypatch, tmp_path, list(synthetic_scan(120, edits)))
    evidence = service.collect(local_video_path=source, task_dir=tmp_path / 'task', transcript_segments=[])
    assert any('text_or_detail_change' in frame.reasons for frame in evidence.frames)
    assert evidence.omitted_changes > 0
    assert len(evidence.frames) <= service.max_frames


def test_extraction_never_overwrites_original_even_through_hardlink(tmp_path):
    source = tmp_path / 'original.mp4'
    source.write_bytes(b'original')
    alias = tmp_path / 'frame.jpg'
    alias.hardlink_to(source)
    with pytest.raises(VideoEvidenceError):
        VideoEvidenceService._extract_frame(source, 0, alias)
    assert source.read_bytes() == b'original'


def test_verified_task_source_cache_reuses_frames_and_refreshes_alignment(monkeypatch, tmp_path):
    service, source, _ = configure_local(monkeypatch, tmp_path, list(synthetic_scan(120)))
    folder = tmp_path / 'task'
    first = service.collect(local_video_path=source, task_dir=folder, transcript_segments=[], owner_id='alice')
    monkeypatch.setattr(service, '_probe_duration', Mock(side_effect=AssertionError('must reuse cache')))
    monkeypatch.setattr(service, '_scan', Mock(side_effect=AssertionError('must reuse cache')))
    second = service.collect(local_video_path=source, task_dir=folder,
        transcript_segments=[TranscriptSegment(0, 120, 'current ASR')], owner_id='alice')
    assert second.cache_hit and first.frames[0].image_path == second.frames[0].image_path
    assert second.frames[0].speech_indices == [0]
    import json
    saved = json.loads((folder / 'video_evidence.json').read_text(encoding='utf-8'))
    assert saved['frames'][0]['speech_indices'] == [0]
    assert str(source) not in str(saved)


@pytest.mark.parametrize('change', ['source', 'path', 'task', 'owner', 'frame', 'manifest'])
def test_cache_rejects_changed_source_scope_or_tampered_material(monkeypatch, tmp_path, change):
    import json
    import shutil
    service, source, _ = configure_local(monkeypatch, tmp_path, list(synthetic_scan(120)))
    folder = tmp_path / 'task'
    result = service.collect(local_video_path=source, task_dir=folder, transcript_segments=[], owner_id='alice')
    owner = 'alice'
    if change == 'source':
        source.write_bytes(b'changed-original')
    elif change == 'path':
        other = tmp_path / 'another.mp4'
        shutil.copy2(source, other)
        source = other
    elif change == 'task':
        other_folder = tmp_path / 'other-task'
        shutil.copytree(folder, other_folder)
        folder = other_folder
    elif change == 'owner':
        owner = 'bob'
    elif change == 'frame':
        result.frames[0].image_path.write_bytes(b'corrupt frame')
    else:
        manifest = folder / 'video_evidence.json'
        data = json.loads(manifest.read_text(encoding='utf-8'))
        data['frames'][0]['relative_path'] = '../original.mp4'
        manifest.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(service, '_probe_duration', Mock(side_effect=VideoEvidenceError('rescan required')))
    with pytest.raises(VideoEvidenceError, match='rescan required'):
        service.collect(local_video_path=source, task_dir=folder, transcript_segments=[], owner_id=owner)


def test_parallel_alignment_updates_saved_evidence_without_rescan(monkeypatch, tmp_path):
    import json
    service, source, _ = configure_local(monkeypatch, tmp_path, list(synthetic_scan(120)))
    folder = tmp_path / 'task'
    evidence = service.collect(local_video_path=source, task_dir=folder, transcript_segments=[])
    evidence.align([TranscriptSegment(0, 120, 'new speech')])
    assert json.loads((folder / 'video_evidence.json').read_text(encoding='utf-8'))['frames'][0]['speech_indices'] == [0]


def test_video_packet_tail_overrides_stale_duration_metadata(monkeypatch, tmp_path):
    import io
    from unittest.mock import MagicMock
    from types import SimpleNamespace
    from app.services import video_evidence_service as module
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        stdout='{"streams":[{"duration":"2"}],"format":{"duration":"2"}}'))
    process = MagicMock()
    process.__enter__.return_value = process
    process.stdout = io.StringIO('0.0,0.1\n5.9,0.1\n')
    process.wait.return_value = 0
    process.poll.return_value = 0
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k: process)
    assert VideoEvidenceService._probe_duration(tmp_path / 'synthetic.webm') == 6.0


def test_webm_uses_seekable_derivative_but_cache_identity_stays_original(monkeypatch, tmp_path):
    import json
    from app.services import video_evidence_service as module
    source = tmp_path / 'original.webm'
    source.write_bytes(b'untouched raw original')
    playable = tmp_path / 'preview.webm'
    playable.write_bytes(b'seekable remux')
    remux = Mock(return_value=playable)
    monkeypatch.setattr(module, 'playback_file', remux)
    service = VideoEvidenceService(max_frames=6, ocr=lambda _: 'visible text')
    probe = Mock(return_value=1)
    scan = Mock(side_effect=lambda *a: synthetic_scan(1))
    extracted = []
    def extract(path, offset, destination):
        extracted.append(path)
        Image.new('RGB', (64, 36), 'red').save(destination)
    monkeypatch.setattr(service, '_probe_duration', probe)
    monkeypatch.setattr(service, '_scan', scan)
    monkeypatch.setattr(service, '_extract_frame', extract)
    folder = tmp_path / 'task'
    service.collect(local_video_path=source, task_dir=folder, transcript_segments=[], owner_id='alice')
    probe.assert_called_once_with(playable)
    assert scan.call_args.args[0] == playable and extracted == [playable]
    saved = json.loads((folder / 'video_evidence.json').read_text(encoding='utf-8'))
    assert saved['source_size'] == source.stat().st_size
    assert saved['source_path_fingerprint'] == service._identity(source.resolve(), folder.resolve(), 'alice')['source_path_fingerprint']
    # A valid derived-frame cache does not require remuxing again.
    assert service.collect(local_video_path=source, task_dir=folder,
                           transcript_segments=[], owner_id='alice').cache_hit
    assert remux.call_count == 1 and probe.call_count == 1
    assert source.read_bytes() == b'untouched raw original'


def test_original_changed_during_remux_does_not_commit_manifest(monkeypatch, tmp_path):
    from app.services import video_evidence_service as module
    service, source, _ = configure_local(monkeypatch, tmp_path, list(synthetic_scan(1)), duration=1)
    webm = source.with_suffix('.webm')
    source.rename(webm)
    def remux(path):
        path.write_bytes(b'changed while remuxing')
        return path
    monkeypatch.setattr(module, 'playback_file', remux)
    with pytest.raises(VideoEvidenceError, match='变化'):
        service.collect(local_video_path=webm, task_dir=tmp_path / 'task', transcript_segments=[])
    assert not (tmp_path / 'task' / 'video_evidence.json').exists()


def test_low_resolution_revision_cache_is_rejected_and_full_resolution_cache_reused(monkeypatch, tmp_path):
    import json
    service, source, _ = configure_local(monkeypatch, tmp_path, list(synthetic_scan(1)), duration=1)
    def full_frame(source, timestamp, destination):
        Image.new('RGB', (1920, 1080), 'white').save(destination)
    monkeypatch.setattr(service, '_extract_frame', full_frame)
    folder = tmp_path / 'task'
    service.collect(local_video_path=source, task_dir=folder, transcript_segments=[])
    reused = service.collect(local_video_path=source, task_dir=folder, transcript_segments=[])
    assert reused.cache_hit
    manifest = folder / 'video_evidence.json'
    saved = json.loads(manifest.read_text(encoding='utf-8'))
    assert saved['version'] > 2
    saved['version'] = 2
    manifest.write_text(json.dumps(saved), encoding='utf-8')
    monkeypatch.setattr(service, '_probe_duration', Mock(side_effect=VideoEvidenceError('must upgrade images')))
    with pytest.raises(VideoEvidenceError, match='must upgrade images'):
        service.collect(local_video_path=source, task_dir=folder, transcript_segments=[])
