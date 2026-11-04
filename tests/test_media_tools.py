from app.media_tools import configure_media_tools


def test_finds_winget_tools_when_missing_from_path(tmp_path, monkeypatch):
    tools = tmp_path / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg_test" / "ffmpeg-build" / "bin"
    tools.mkdir(parents=True)
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        (tools / name).touch()
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    configure_media_tools(windows=True)
    import os
    assert str(tools) in os.environ["PATH"]
