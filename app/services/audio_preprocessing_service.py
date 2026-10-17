"""Conservative meeting denoising without cutting or shifting the timeline."""
import subprocess
from pathlib import Path


MEETING_FILTER = "highpass=f=80,lowpass=f=7600,afftdn=nr=8:nf=-35:tn=1"


def prepare_meeting_audio(source: str, destination: Path) -> dict:
    """Retain the original file; write denoised 16 kHz mono float samples."""
    subprocess.run([
        "ffmpeg", "-nostdin", "-y", "-v", "error", "-i", source,
        "-vn", "-af", MEETING_FILTER, "-ar", "16000", "-ac", "1",
        "-f", "f32le", str(destination),
    ], check=True, capture_output=True, timeout=3600)
    return {"version": "meeting-denoise-v1", "sample_rate": 16000,
            "channels": 1, "filter": MEETING_FILTER, "timeline_preserved": True}
