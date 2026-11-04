"""Locate development media tools when Windows has not refreshed its PATH."""
import os
from pathlib import Path
import shutil


def configure_media_tools(*, windows=None):
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    if windows is None:
        windows = os.name == "nt"
    local = os.environ.get("LOCALAPPDATA")
    if not windows or not local:
        return
    packages = Path(local) / "Microsoft" / "WinGet" / "Packages"
    for executable in sorted(packages.glob("Gyan.FFmpeg*/ffmpeg*/bin/ffmpeg.exe"), reverse=True):
        folder = executable.parent
        if (folder / "ffprobe.exe").is_file():
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
            return
