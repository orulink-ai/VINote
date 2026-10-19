import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.media_playback_service import playback_file


def test_preview_remuxes_webm_once_without_replacing_original(tmp_path, monkeypatch):
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


def test_changed_source_cannot_reuse_old_preview(tmp_path, monkeypatch):
    source = tmp_path / 'source.webm'
    source.write_bytes(b'first')
    monkeypatch.setattr(subprocess, 'run', lambda cmd, **kw: Path(cmd[-1]).write_bytes(b'preview'))
    first = playback_file(source)
    source.write_bytes(b'changed original')
    assert playback_file(source) != first


def test_failed_remux_is_not_cached_or_misreported_missing(tmp_path, monkeypatch):
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
