import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.media_playback_service import playback_file
from app.services import media_playback_service as service


@pytest.fixture
def proof(monkeypatch):
    def manifest(path):
        data = path.read_bytes()
        if data == b'corrupt':
            raise ValueError('Invalid media')
        return {'streams': ('short' if data == b'incomplete' else 'complete',),
                'end': 10.0, 'video': True}
    monkeypatch.setattr(service, '_packet_manifest', manifest, raising=False)
    monkeypatch.setattr(service, '_check_index', lambda *args: None, raising=False)


def test_preview_remuxes_webm_once_without_replacing_original(tmp_path, monkeypatch, proof):
    source = tmp_path / 'source_video.webm'
    source.write_bytes(b'original immutable video')
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[command.index('-c') + 1] == 'copy'
        Path(command[-1]).write_bytes(b'seekable preview')
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, 'run', run)
    preview = playback_file(source)
    assert preview != source and preview.read_bytes() == b'seekable preview'
    assert source.read_bytes() == b'original immutable video'
    assert playback_file(source) == preview
    assert len(calls) == 1


def test_changed_source_cannot_reuse_old_preview(tmp_path, monkeypatch, proof):
    source = tmp_path / 'source.webm'
    source.write_bytes(b'first')
    monkeypatch.setattr(subprocess, 'run', lambda cmd, **kw: Path(cmd[-1]).write_bytes(b'preview'))
    first = playback_file(source)
    source.write_bytes(b'changed original')
    assert playback_file(source) != first


def test_failed_remux_is_not_cached_or_misreported_missing(tmp_path, monkeypatch, proof):
    source = tmp_path / 'source.webm'
    source.write_bytes(b'original')

    def fail(command, **kwargs):
        Path(command[-1]).write_bytes(b'incomplete')
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, 'run', fail)
    with pytest.raises(HTTPException) as error:
        playback_file(source)
    assert error.value.status_code == 409
    assert source.read_bytes() == b'original'
    assert not list((tmp_path / '.playback-preview').glob('*'))


def test_other_containers_unchanged_and_symlink_cache_rejected(tmp_path):
    mp4 = tmp_path / 'source.mp4'
    mp4.write_bytes(b'original')
    assert playback_file(mp4) == mp4
    source = tmp_path / 'source.webm'
    source.write_bytes(b'original')
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    try:
        (tmp_path / '.playback-preview').symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip('symlink creation unavailable')
    with pytest.raises(HTTPException):
        playback_file(source)


def test_nonempty_truncated_cache_is_not_served_and_is_rebuilt(tmp_path, monkeypatch, proof):
    source = tmp_path / 'source.webm'
    source.write_bytes(b'original')
    calls = []
    def remux(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b'complete preview')
    monkeypatch.setattr(subprocess, 'run', remux)
    preview = playback_file(source)
    preview.write_bytes(b'incomplete')
    assert playback_file(source).read_bytes() == b'complete preview'
    assert len(calls) == 2 and source.read_bytes() == b'original'


def test_ffmpeg_exit_zero_with_short_output_is_not_success(tmp_path, monkeypatch, proof):
    source = tmp_path / 'source.webm'
    source.write_bytes(b'original')
    monkeypatch.setattr(subprocess, 'run', lambda cmd, **kw:
                        Path(cmd[-1]).write_bytes(b'incomplete'))
    with pytest.raises(HTTPException) as caught:
        playback_file(source)
    assert caught.value.status_code == 409
    assert source.read_bytes() == b'original'
    assert not list((tmp_path / '.playback-preview').glob('*'))


def test_invalid_cached_preview_and_failed_rebuild_never_fall_back_to_success(
        tmp_path, monkeypatch, proof):
    source = tmp_path / 'source.webm'
    source.write_bytes(b'original')
    monkeypatch.setattr(subprocess, 'run', lambda cmd, **kw:
                        Path(cmd[-1]).write_bytes(b'complete preview'))
    preview = playback_file(source)
    preview.write_bytes(b'corrupt')
    def fail(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 120)
    monkeypatch.setattr(subprocess, 'run', fail)
    with pytest.raises(HTTPException) as caught:
        playback_file(source)
    assert caught.value.status_code == 409
    assert source.read_bytes() == b'original'


def test_source_change_during_proof_is_rejected(tmp_path, monkeypatch, proof):
    source = tmp_path / 'source.webm'
    source.write_bytes(b'original')
    monkeypatch.setattr(subprocess, 'run', lambda cmd, **kw:
                        Path(cmd[-1]).write_bytes(b'complete preview'))
    def changed(*args):
        source.write_bytes(b'changed original during validation')
    monkeypatch.setattr(service, '_check_index', changed)
    with pytest.raises(HTTPException) as caught:
        playback_file(source)
    assert caught.value.status_code == 409


def test_index_validation_failure_does_not_publish_preview(tmp_path, monkeypatch, proof):
    source = tmp_path / 'source.webm'
    source.write_bytes(b'original')
    monkeypatch.setattr(subprocess, 'run', lambda cmd, **kw:
                        Path(cmd[-1]).write_bytes(b'complete preview'))
    def fail(*args):
        raise ValueError('Missing index/duration')
    monkeypatch.setattr(service, '_check_index', fail)
    with pytest.raises(HTTPException):
        playback_file(source)
    assert not list((tmp_path / '.playback-preview').glob('*'))


def test_cache_directory_permission_error_is_bounded_and_original_kept(tmp_path, monkeypatch):
    source = tmp_path / 'source.webm'
    source.write_bytes(b'original')
    mkdir = Path.mkdir
    def denied(path, *args, **kwargs):
        if path.name == '.playback-preview':
            raise PermissionError('private-path-must-not-escape')
        return mkdir(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'mkdir', denied)
    with pytest.raises(HTTPException) as caught:
        playback_file(source)
    assert caught.value.status_code == 409
    assert 'private-path' not in caught.value.detail
    assert source.read_bytes() == b'original'


def test_failed_fsync_never_publishes_uncommitted_preview(tmp_path, monkeypatch, proof):
    source = tmp_path / 'source.webm'
    source.write_bytes(b'original')
    monkeypatch.setattr(subprocess, 'run', lambda cmd, **kw:
                        Path(cmd[-1]).write_bytes(b'complete preview'))
    def failed(*args):
        raise OSError('injected flush failure')
    monkeypatch.setattr(service.os, 'fsync', failed)
    with pytest.raises(HTTPException) as caught:
        playback_file(source)
    assert caught.value.status_code == 409
    assert not list((tmp_path / '.playback-preview').glob('*'))
    assert source.read_bytes() == b'original'


def test_busy_preview_lock_does_not_launch_ffmpeg(tmp_path, monkeypatch):
    from unittest.mock import Mock
    source = tmp_path / 'source.webm'
    source.write_bytes(b'original')
    lock = Mock()
    lock.acquire.return_value = False
    monkeypatch.setattr(service, '_REMUX_LOCK', lock)
    run = Mock(side_effect=AssertionError('No process while busy'))
    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(HTTPException) as caught:
        playback_file(source)
    assert caught.value.status_code == 409
    run.assert_not_called()
    lock.release.assert_not_called()


@pytest.mark.parametrize('duration', ['NaN', 'Infinity', '-1', '1', None, {}, []])
def test_invalid_or_short_container_duration_cannot_pass_index_check(duration, monkeypatch, tmp_path):
    import json
    def probe(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0,
            stdout=json.dumps({'format': {'duration': duration}}).encode(), stderr=b'')
    monkeypatch.setattr(subprocess, 'run', probe)
    with pytest.raises((ValueError, TypeError)):
        service._check_index(tmp_path / 'synthetic.webm', {'end': 10, 'video': True})
