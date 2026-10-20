"""Small generated fixtures exercise actual local FFmpeg, never provider/media data."""
import hashlib
import shutil
import subprocess

import pytest

from app.services.video_evidence_service import VideoEvidenceService

pytestmark = pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),
                                reason='local FFmpeg is required')


@pytest.mark.parametrize('seconds', [0.2, 2.5, 6.2])
def test_actual_video_tail_beyond_audio_is_scanned_and_original_is_unchanged(tmp_path, seconds):
    source = tmp_path / 'synthetic.webm'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-threads', '1', '-filter_threads', '1',
        '-f', 'lavfi', '-i', f'testsrc2=size=160x90:rate=10:duration={seconds}',
        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.1',
        '-c:v', 'libvpx', '-threads', '1', '-c:a', 'libopus', str(source)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    evidence = VideoEvidenceService(max_frames=8, ocr=lambda _: 'synthetic fixture').collect(
        local_video_path=source, task_dir=tmp_path / 'task', transcript_segments=[])
    assert evidence.duration >= seconds - .1
    assert evidence.scanned_samples >= int(seconds)
    assert max(t for frame in evidence.frames for t in frame.sample_offsets) >= seconds - 1.1
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert (tmp_path / 'task' / 'video_evidence.json').is_file()


@pytest.mark.parametrize('source_size,expected', [('1920x1080', (1920, 1080)),
                                                ('2560x1440', (1920, 1080)),
                                                ('640x360', (640, 360))])
def test_full_resolution_extraction_caps_without_upscaling(tmp_path, source_size, expected):
    from PIL import Image
    source = tmp_path / 'synthetic.mp4'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-threads', '1', '-filter_threads', '1',
                    '-f', 'lavfi', '-i', f'color=c=white:s={source_size}:d=0.2:r=10',
                    '-c:v', 'libx264', '-threads', '1', str(source)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = tmp_path / 'frame.jpg'
    VideoEvidenceService._extract_frame(source, 0, destination)
    with Image.open(destination) as image:
        assert image.size == expected
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
