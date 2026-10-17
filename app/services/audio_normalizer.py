"""
Re-encodes recorded audio into a canonical WAV before it reaches the
transcriber.

Why this exists
---------------
Browser MediaRecorder (especially in Tauri / WKWebView on macOS) sometimes
produces a webm container whose EBML header is malformed or shifted, e.g. the
file starts with the ChapterAtom ID (`0x1F43B675`) instead of the EBML magic
(`0x1A45DFA3`). libavformat's strict demuxer rejects such files with the
generic error:

    Invalid data found when processing input

Re-encoding through ffmpeg with ``-err_detect ignore_err -fflags
+discardcorrupt`` recovers the audio stream and produces a clean file that
both faster-whisper and openai-whisper can decode without warnings.

The function is idempotent: if the input is already a valid audio file that
ffprobe can read without errors, it is left untouched. The output is always
16 kHz mono PCM WAV at `upload_path.with_suffix('.wav')`, which both the
existing transcription path and faster-whisper consume natively.

The original upload is preserved next to the normalized file so the user can
still download the original recording from the note detail page.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _ffprobe_readable(file_path: Path) -> bool:
    """Return True when ffprobe can read the audio header without errors."""
    if not file_path.exists() or file_path.stat().st_size == 0:
        return False
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-hide_banner",
                "-show_entries",
                "stream=codec_type,codec_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if result.returncode != 0:
            return False
        # At least one audio stream must be reported.
        return any(line.strip().startswith("audio") for line in result.stdout.splitlines())
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("[AudioNormalizer] ffprobe unavailable: %s", exc)
        return False


def _reencode_to_wav(source: Path, target: Path) -> bool:
    """Re-encode the source into 16kHz mono PCM WAV. Returns True on success."""
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-err_detect",
        "ignore_err",
        "-fflags",
        "+discardcorrupt",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(target),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.error("[AudioNormalizer] ffmpeg failed to launch: %s", exc)
        return False
    if result.returncode != 0:
        logger.warning(
            "[AudioNormalizer] ffmpeg re-encode failed (exit=%s) stderr=%s",
            result.returncode,
            result.stderr.strip()[-500:],
        )
        return False
    return target.exists() and target.stat().st_size > 0


def normalize_audio_for_transcription(upload_path: Path) -> Path:
    """Return the path the transcriber should consume.

    If the uploaded file is already a readable audio file, returns it
    unchanged. If ffprobe rejects it (corrupt header, partial cluster, etc.)
    this runs an ffmpeg recovery re-encode into ``upload_path.with_suffix('.wav')``
    next to the original and returns the WAV path.
    """
    if not upload_path.exists():
        return upload_path

    if _ffprobe_readable(upload_path):
        return upload_path

    logger.info(
        "[AudioNormalizer] %s is unreadable by ffprobe; re-encoding to WAV",
        upload_path.name,
    )
    wav_target = upload_path.with_suffix(".wav")
    if _reencode_to_wav(upload_path, wav_target):
        return wav_target

    # Last resort: leave the original file in place. The transcriber will
    # surface the same ffmpeg error it always did, but we don't make things
    # worse by deleting user data.
    logger.warning(
        "[AudioNormalizer] could not produce a normalized WAV for %s; leaving original",
        upload_path.name,
    )
    return upload_path