"""Actual local FFmpeg/Range coverage; private originals are opt-in and read-only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.routers import note_library, files
from app.services import media_playback_service as service

pytestmark = pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),
                                reason='Actual local FFmpeg and ffprobe required')


@pytest.fixture
def video(tmp_path, request):
    video_seconds, audio_seconds = getattr(request, 'param', (8, 5))
    path = tmp_path / 'source.webm'
    subprocess.run([
        'ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
        f'testsrc2=size=96x64:rate=4:duration={video_seconds}', '-f', 'lavfi', '-i',
        f'sine=frequency=440:sample_rate=48000:duration={audio_seconds}', '-threads', '1',
        '-c:v', 'libvpx', '-deadline', 'realtime', '-cpu-used', '8',
        '-c:a', 'libopus', '-f', 'webm', '-live', '1', str(path),
    ], check=True, capture_output=True, timeout=30)
    return path


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def client_for(source, monkeypatch, tmp_path):
    owner = SimpleNamespace(user_id='owner')
    note = SimpleNamespace(task_id='sample-task', source_type='meeting_video')
    repository = SimpleNamespace(get_note=lambda user, key: note if user == 'owner' else None)
    monkeypatch.setattr(note_library, '_repository', repository)
    monkeypatch.setattr(note_library, '_artifact_service', SimpleNamespace(
        find_task_dir=lambda task: tmp_path, resolve_source_media=lambda task: source))
    app = FastAPI()
    app.include_router(note_library.router, prefix='/api')
    app.dependency_overrides[note_library.get_current_user] = lambda: owner
    return TestClient(app), owner


def exercise_ranges(source, monkeypatch, tmp_path):
    """Use the production route and Starlette range implementation, not a mock response."""
    before = digest(source)
    cache = tmp_path / 'isolated-preview'
    monkeypatch.setattr(service, '_preview_folder', lambda path: cache)
    preview = service.playback_file(source)
    proof = service._packet_manifest(source)
    assert service._packet_manifest(preview)['streams'] == proof['streams']
    size = preview.stat().st_size
    client, owner = client_for(source, monkeypatch, tmp_path)
    url = '/api/notes/fixture/media?playback=true'
    stamp = service._stamp(preview)
    with client:
        for start, end in [(0, 1023), (size // 2, size // 2 + 1023), (size - 65536, size - 1)]:
            start = max(0, start)
            with preview.open('rb') as disk:
                disk.seek(start)
                expected = disk.read(end - start + 1)
            response = client.get(url, headers={'Range': f'bytes={start}-{end}'})
            assert response.status_code == 206
            assert response.headers['content-range'] == f'bytes {start}-{end}/{size}'
            assert response.headers['content-length'] == str(len(expected))
            assert response.headers['cache-control'] == 'private, no-store'
            assert response.content == expected
        suffix = client.get(url, headers={'Range': 'bytes=-512'})
        assert suffix.status_code == 206
        with preview.open('rb') as disk:
            disk.seek(-512, 2)
            assert suffix.content == disk.read()
        outside = client.get(url, headers={'Range': f'bytes={size}-'})
        assert outside.status_code == 416
        assert outside.headers['content-range'] == f'*/{size}'
        # Simulate a new process's empty proof cache, without restarting anything.
        service._VERIFIED.clear()
        assert client.get(url, headers={'Range': 'bytes=0-0'}).status_code == 206
        assert service._stamp(preview) == stamp  # Verified reuse, no rewrite.
        exported = client.get('/api/notes/fixture/media', headers={'Range': 'bytes=-512'})
        with source.open('rb') as disk:
            disk.seek(-512, 2)
            assert exported.status_code == 206 and exported.content == disk.read()
        owner.user_id = 'foreign'
        assert client.get(url).status_code == 404
    assert digest(source) == before
    return preview, proof


def test_actual_indexed_full_video_tail_range_reload_and_original_export(video, monkeypatch, tmp_path):
    preview, proof = exercise_ranges(video, monkeypatch, tmp_path)
    assert proof['end'] > 7.5  # Video survives audio ending around 5 seconds.
    assert preview != video


@pytest.mark.parametrize('video', [(5, 8)], indirect=True)
def test_audio_continuing_after_video_is_not_mistaken_for_broken_tail(video):
    preview = service.playback_file(video)
    assert service._packet_manifest(preview)['end'] > 7.5


def test_real_truncated_nonempty_cache_is_rebuilt_with_complete_packets(video, monkeypatch):
    before = digest(video)
    preview = service.playback_file(video)
    with preview.open('r+b') as corrupt:
        corrupt.truncate(preview.stat().st_size // 3)
    restored = service.playback_file(video)
    assert service._packet_manifest(restored)['streams'] == service._packet_manifest(video)['streams']
    assert digest(video) == before


def test_real_ffmpeg_exit_zero_short_remux_is_rejected(video, monkeypatch):
    original = subprocess.run
    def short(command, **kwargs):
        if command[-2] == 'webm':
            command = command[:-1] + ['-t', '1', command[-1]]
        return original(command, **kwargs)
    monkeypatch.setattr(subprocess, 'run', short)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        service.playback_file(video)
    assert caught.value.status_code == 409
    assert not list((video.parent / '.playback-preview').glob('*'))


def test_webm_suffix_cannot_enable_remote_playlist_or_protocol_fallback(tmp_path, monkeypatch):
    from fastapi import HTTPException
    source = tmp_path / 'disguised.webm'
    content = b'#EXTM3U\n#EXTINF:8,\nhttps://example.invalid/never-fetch.ts\n'
    source.write_bytes(content)
    original, calls = subprocess.run, []
    def capture(command, **kwargs):
        calls.append(command)
        return original(command, **kwargs)
    monkeypatch.setattr(subprocess, 'run', capture)
    with pytest.raises(HTTPException) as caught:
        service.playback_file(source)
    assert caught.value.status_code == 409
    assert len(calls) == 1
    assert calls[0][calls[0].index('-protocol_whitelist') + 1] == 'file,pipe'
    assert calls[0][calls[0].index('-f') + 1] == 'matroska'
    assert source.read_bytes() == content


@pytest.mark.parametrize('identifier', ['fixture', 'task:fixture'])
def test_file_content_explicit_preview_and_download_precedence(video, monkeypatch, identifier):
    from fastapi import HTTPException
    from unittest.mock import Mock
    owner = SimpleNamespace(user_id='owner')
    def get(user, key):
        if user != 'owner':
            raise HTTPException(404, 'Not found')
        return {'media_type': 'video/webm', 'filename': 'fixture.webm'}, video
    monkeypatch.setattr(files, 'service', SimpleNamespace(get=get))
    app = FastAPI()
    app.include_router(files.router, prefix='/api')
    app.dependency_overrides[files.get_current_user] = lambda: owner
    app.dependency_overrides[files.local_only] = lambda: None
    original = video.read_bytes()
    url = f'/api/files/{identifier}/content'
    with TestClient(app) as client:
        response = client.get(url + '?playback=true', headers={'Range': 'bytes=-512'})
        preview = service.playback_file(video)
        assert response.status_code == 206
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['x-content-type-options'] == 'nosniff'
        with preview.open('rb') as disk:
            disk.seek(-512, 2)
            assert response.content == disk.read()
        remux = Mock(side_effect=HTTPException(409, 'Preview unavailable'))
        monkeypatch.setattr(service, 'playback_file', remux)
        failed = client.get(url + '?playback=true')
        assert failed.status_code == 409
        remux.assert_called_once()
        remux.reset_mock()
        for suffix in ['', '?download=true', '?download=true&playback=true']:
            exported = client.get(url + suffix)
            assert exported.status_code == 200 and exported.content == original
        remux.assert_not_called()
        owner.user_id = 'foreign'
        assert client.get(url + '?playback=true').status_code == 404
        remux.assert_not_called()
    assert video.read_bytes() == original


@pytest.mark.parametrize('sample', ['A', 'B'])
def test_private_complete_source_and_tail_ranges(sample, monkeypatch, tmp_path):
    manifest = os.environ.get('VINOTE_PRIVATE_PLAYBACK_TESTSET')
    if not manifest:
        pytest.skip('Explicit private, read-only source manifest required')
    rows = json.loads(Path(manifest).read_text(encoding='utf-8-sig'))
    row = next(item for item in rows if item['sample'] == sample)
    source = Path(row['source'])
    assert digest(source) == row['sha256']
    preview, proof = exercise_ranges(source, monkeypatch, tmp_path)
    assert abs(proof['end'] - row['duration']) < .25
    print(f"sample={sample} full_end={proof['end']:.3f} tracks={len(proof['streams'])} "
          f"packets={sum(track[4] for track in proof['streams'])} "
          f"track_counts={[(track[1], track[4]) for track in proof['streams']]} "
          f"track_ends={proof['tails']} "
          f"range_and_tail=passed original_unchanged={digest(source) == row['sha256']}")
