"""VILab's native HTTP file transcription API (not OpenAI audio)."""
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from fastapi import HTTPException

from app.models.transcript import TranscriptResult, TranscriptSegment
from app.transcribers.base import Transcriber


class VILabTranscriber(Transcriber):
    def __init__(self, base_url: str, api_key: str, model: str | None = None, language: str | None = None, cloud_user_id: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.language = language
        self.cloud_user_id = cloud_user_id

    def transcribe(self, file_path: str) -> TranscriptResult:
        # Native streaming providers accept 16 kHz mono PCM WAV, including HTTP uploads.
        with tempfile.TemporaryDirectory(prefix="vinote-stt-") as folder:
            normalized = str(Path(folder) / "audio.wav")
            try:
                subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", file_path,
                                "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", normalized],
                               check=True, capture_output=True, timeout=600)
            except (subprocess.SubprocessError, OSError):
                raise RuntimeError("无法转换音频，请检查 ffmpeg 和输入文件") from None
            for attempt in range(3):
                try:
                    return self._transcribe_normalized(normalized)
                except (HTTPException, RuntimeError) as exc:
                    # Retry only explicit transient gateway failures. Authentication,
                    # validation and unknown failures remain visible immediately.
                    detail = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
                    transient = any(f"HTTP {code}" in detail for code in (502, 503, 504))
                    if not transient or attempt == 2:
                        raise
                    time.sleep(attempt + 1)

    def _transcribe_normalized(self, file_path: str) -> TranscriptResult:
        # Streaming ASR may consume the upload at real-time speed.
        duration = float(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path,
        ], text=True, timeout=30).strip())
        timeout = httpx.Timeout(max(600, duration * 1.5 + 120), connect=10)
        fields = {}
        if self.model:
            fields["model"] = self.model
        if self.language:
            fields["language"] = self.language
        if self.cloud_user_id:
            from app.services.vilab_cloud_service import VILabCloudService

            with Path(file_path).open("rb") as audio:
                payload = VILabCloudService().request(self.cloud_user_id, "POST", "/v1/asr/transcriptions",
                    files={"file": (Path(file_path).name, audio, "application/octet-stream")}, data=fields, timeout=timeout)
            return self._result(payload, file_path)
        with Path(file_path).open("rb") as audio:
            try:
                response = httpx.post(
                    f"{self.base_url}/v1/asr/transcriptions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"file": (Path(file_path).name, audio, "application/octet-stream")},
                    data=fields, timeout=timeout,
                )
            except httpx.RequestError:
                raise RuntimeError("VILab STT connection failed or timed out") from None
        if not response.is_success:
            # Do not echo upstream bodies: they may contain credentials.
            raise RuntimeError(f"VILab STT returned HTTP {response.status_code}")
        return self._result(response.json(), file_path)

    def _result(self, payload, file_path):
        text = str(payload.get("text") or "").strip()
        if not text:
            raise RuntimeError("VILab STT returned an empty transcript")
        duration = float(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path,
        ], text=True, timeout=30).strip())
        # Preserve provider evidence when available; never synthesize speakers.
        segments = []
        for item in payload.get("segments") or []:
            if not isinstance(item, dict) or not str(item.get("text") or "").strip():
                continue
            try:
                start, end = float(item["start"]), float(item["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if not 0 <= start <= end <= duration + 1:
                continue
            speaker = item.get("speaker_id", item.get("speaker"))
            segments.append(TranscriptSegment(
                start=start, end=end, text=str(item["text"]), raw_text=str(item["text"]),
                speaker_id=str(speaker) if speaker is not None else None,
                speaker_label=item.get("speaker_label"),
            ))
        has_timestamps = bool(segments)
        if not segments:
            segments = [TranscriptSegment(start=0, end=duration, text=text, raw_text=text)]
        return TranscriptResult(
            language=payload.get("language") or self.language,
            full_text=text,
            segments=segments,
            metadata={
                "provider": "vliab-server",
                "timestamp_granularity": "segment" if has_timestamps else "file",
                "speaker_diarization": any(segment.speaker_id is not None for segment in segments),
            },
        )
