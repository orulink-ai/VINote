"""Small cached waveform previews; never load complete decoded audio into memory."""
import hashlib
import json
import math
import subprocess
import threading
from pathlib import Path

from fastapi import HTTPException

from app.services.transcription_service import TranscriptionService

_worker = threading.BoundedSemaphore(1)
POINTS = 96


def recording_waveform(source: Path, folder: Path) -> dict:
    stat = source.stat()
    fingerprint = hashlib.sha256(
        f"v2:{source.name}:{stat.st_size}:{stat.st_mtime_ns}".encode()
    ).hexdigest()
    cache = folder / "waveform-preview.json"
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if saved.get("fingerprint") == fingerprint:
            return {"duration": saved["duration"], "peaks": saved["peaks"]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    if not _worker.acquire(blocking=False):
        raise HTTPException(503, "正在准备另一份录音预览，请稍后重试")
    try:
        duration = TranscriptionService.get_audio_duration(str(source))
        if not math.isfinite(duration) or not 0 < duration <= 7200:
            raise HTTPException(422, "暂时无法准备此录音的波形，原文件仍可播放和导出")
        samples = max(1, math.ceil(duration * 8000 / POINTS))
        result = subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-threads", "1",
            "-i", str(source), "-vn", "-ac", "1", "-ar", "8000",
            "-af", f"aresample=8000,aformat=channel_layouts=mono,asetnsamples=n={samples},astats=metadata=1:reset=1,"
            "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
            "-f", "null", "-",
        ], capture_output=True, text=True, check=True, timeout=60)
        levels = []
        for line in result.stdout.splitlines():
            if line.startswith("lavfi.astats.Overall.RMS_level="):
                db = float(line.split("=", 1)[1])
                levels.append(10 ** (min(0.0, db) / 20) if math.isfinite(db) else 0.0)
        if not levels:
            raise HTTPException(422, "录音波形暂不可用，原文件仍可播放和导出")
        levels = levels[:POINTS]
        maximum = max(levels)
        peaks = [round(value / maximum, 4) if maximum else 0.0 for value in levels]
        payload = {"duration": duration, "peaks": peaks}
        temporary = cache.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps({**payload, "fingerprint": fingerprint}), encoding="utf-8")
            temporary.replace(cache)
        except OSError:
            pass  # A read-only artifact directory must not block playback.
        return payload
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise HTTPException(503, "录音预览未准备成功，请重试；原文件仍保留") from exc
    finally:
        _worker.release()
