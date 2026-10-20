from unittest.mock import Mock

from app.services.screenshot_service import ScreenshotService
from app.services.video_evidence_service import VideoEvidenceService, VideoEvidenceError


def test_no_implicit_network_download_for_generated_marker(tmp_path):
    downloader = Mock()
    result = ScreenshotService(downloader).inject_screenshots(video_url='https://example.com/video',
        markdown='claim [[Screenshot:01:00]]', task_dir=tmp_path, task_id='task', media_url='/media')
    assert result == 'claim '
    downloader.download_video.assert_not_called()


def test_failed_frame_does_not_shift_successful_frame_to_another_timestamp(tmp_path, monkeypatch):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'synthetic source')
    offsets = []
    def extract(source, offset, destination):
        offsets.append(offset)
        if offset == 60:
            raise VideoEvidenceError('missing frame')
        destination.write_bytes(b'synthetic JPEG')
    monkeypatch.setattr(VideoEvidenceService, '_extract_frame', extract)
    result = ScreenshotService(Mock()).inject_screenshots(video_url='',
        markdown='first [[Screenshot:01:00]] second [[Screenshot:125:12]]', task_dir=tmp_path,
        task_id='task', media_url='/media', local_video_path=source)
    assert offsets == [60, 7512]
    assert 'Screenshot 01:00' not in result
    assert 'Screenshot 125:12' in result and 't=7512' in result
    assert '[[Screenshot:' not in result
