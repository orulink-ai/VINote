"""Read existing source-bound visual material without scanning or modifying donors."""
from pathlib import Path

from app.services.video_evidence_service import VideoEvidenceService
from app.services.task_generation_context import _unavailable


def retained_visual_evidence(artifacts, folder: Path, canonical: str, source: Path, owner: str):
    service = VideoEvidenceService()
    original = artifacts.find_task_dir(canonical)
    for candidate in dict.fromkeys([folder, original]):
        if candidate is None:
            continue
        path = candidate / 'video_evidence.json'
        if not path.exists() and not path.is_symlink():
            continue
        evidence = service._load(candidate, service._identity(source, candidate.resolve(), owner))
        if evidence is None:
            _unavailable('summary_visual_evidence_unavailable', '已保存的视频证据已变化或无法核验，未重新扫描。')
        # align() may write its manifest; donor material is immutable here.
        evidence._manifest_path = None
        evidence._manifest_payload = None
        from app.services.video_evidence_service import _frame_digest
        evidence._summary_frame_hashes = {frame.image_path: _frame_digest(frame.image_path) for frame in evidence.frames}
        return evidence
    return None


def visual_version(evidence):
    if evidence is None:
        return None
    from app.services.meeting_summary_regeneration import _digest
    from app.services.video_evidence_service import _frame_digest
    return _digest({'duration': evidence.duration, 'frames': [
        {'timestamp': frame.timestamp, 'offsets': frame.sample_offsets,
         'ocr': frame.ocr_text, 'ocr_status': frame.ocr_status,
         'sha256': _frame_digest(frame.image_path)} for frame in evidence.frames]})
