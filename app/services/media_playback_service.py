"""Seekable WebM playback derivatives; exports always retain the original bytes."""
import hashlib
import os
import subprocess
import threading
import uuid
from pathlib import Path

from fastapi import HTTPException

_REMUX_LOCK = threading.Lock()


def playback_file(source: Path) -> Path:
    """Only call after the route has authorized and resolved the original.

    MediaRecorder WebM may omit duration/Cues. A disk-to-disk stream copy
    finalizes those indexes without decoding video or changing the original.
    """
    if source.is_symlink() or not source.is_file():
        raise HTTPException(404, '原文件不可用')
    if source.suffix.lower() != '.webm':
        return source
    source = source.resolve()
    stamp = source.stat()
    identity = f'{source}\0{stamp.st_size}\0{stamp.st_mtime_ns}'
    key = hashlib.sha256(identity.encode()).hexdigest()
    folder = source.parent / '.playback-preview'
    if folder.is_symlink():
        raise HTTPException(409, '预览位置异常，原文件仍可导出')
    folder.mkdir(exist_ok=True)
    target = folder / f'{key}.webm'
    if target.is_symlink():
        raise HTTPException(409, '预览位置异常，原文件仍可导出')
    if target.is_file() and target.stat().st_size:
        return target
    if not _REMUX_LOCK.acquire(timeout=60):
        raise HTTPException(409, '视频预览正在准备，请稍后重新加载')
    temporary = folder / f'{uuid.uuid4().hex}.tmp.webm'
    try:
        if target.is_file() and not target.is_symlink() and target.stat().st_size:
            return target
        subprocess.run([
            'ffmpeg', '-nostdin', '-y', '-v', 'error', '-threads', '1',
            '-i', str(source), '-map', '0:v:0?', '-map', '0:a:0?',
            '-c', 'copy', '-f', 'webm', str(temporary),
        ], check=True, capture_output=True, timeout=120)
        if not temporary.is_file() or not temporary.stat().st_size:
            raise ValueError('Empty preview')
        current = source.stat()
        if (current.st_size, current.st_mtime_ns) != (stamp.st_size, stamp.st_mtime_ns):
            raise ValueError('Source changed')
        os.replace(temporary, target)
        return target
    except (OSError, subprocess.SubprocessError, ValueError):
        raise HTTPException(409, '视频预览准备失败，可重新加载或导出原文件') from None
    finally:
        temporary.unlink(missing_ok=True)
        _REMUX_LOCK.release()
