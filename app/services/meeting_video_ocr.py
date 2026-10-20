"""Child-scoped offline OCR enrichment; frozen donors are never rewritten.

This is material preparation, not execution authority. The caller must already
own the admitted task. Existing source/context and model checks remain intact.
"""
import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path

from app.services.video_evidence_service import _frame_digest, VideoEvidenceError

_MAX_TEXT = 160000
_MAX_RECEIPT = 12 * 1024 * 1024


def _is_windows():
    return os.name == 'nt'


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def prepare_meeting_video_ocr(evidence, *, task_dir, task_id, owner, context_binding):
    """Use installed Windows OCR once before inference, only on desktop tasks.

    Raw ASR, frame bytes, old manifests and old summaries are not changed. A
    failed/unsupported OCR batch supplies no partial text; original images and
    any existing OCR remain available to their existing model capability gate.
    Never reenter this material-preparation step to recover a model request.
    """
    if not _is_windows() or evidence is None:
        return evidence
    folder = Path(task_dir)
    client = folder / 'generation_client'
    if not client.exists():
        return evidence
    if client.is_symlink():
        raise VideoEvidenceError('本次画面文字材料无法核验')
    if client.read_text(encoding='utf-8').strip() != 'desktop':
        return evidence
    if (folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)()
            or not owner or not task_id or not isinstance(context_binding, dict)
            or set(context_binding) != {'context_revision', 'source_version', 'snapshot_sha256'}
            or not all(isinstance(value, str) and value for value in context_binding.values())):
        raise VideoEvidenceError('本次画面文字材料无法核验')
    for name, expected in [('.task_id', task_id), ('recording_owner', owner)]:
        path = folder / name
        if path.is_symlink() or path.read_text(encoding='utf-8') != expected:
            raise VideoEvidenceError('本次画面文字材料与会议不匹配')
    destination = folder / 'meeting_video_ocr.json'
    if destination.exists() or destination.is_symlink():
        raise VideoEvidenceError('本次画面文字准备已有记录，请查询原任务')
    expected_hashes = getattr(evidence, '_summary_frame_hashes', {})
    source_frames = []
    for frame in evidence.frames:
        digest = _frame_digest(frame.image_path)
        if expected_hashes.get(frame.image_path) != digest:
            raise VideoEvidenceError('会议画面已变化，未调用模型')
        source_frames.append({'timestamp': frame.timestamp,
            'sample_offsets': frame.sample_offsets, 'sha256': digest,
            'original_ocr': frame.ocr_text, 'original_ocr_status': frame.ocr_status})
    # Imported lazily: non-Windows and cloud clients never launch this process.
    from app.services.windows_ocr import OCRInput, OCRLimits, recognize_batch
    result = recognize_batch([OCRInput(frame.image_path, row['sha256'])
        for frame, row in zip(evidence.frames, source_frames)],
        limits=OCRLimits(max_images=64))
    derived = copy.deepcopy(evidence)
    derived._manifest_path = None
    derived._manifest_payload = None
    status = result.status
    items = list(result.items)
    if status == 'completed' and not result.inputs_verified_after:
        raise VideoEvidenceError('画面文字未完成原图后验核对，未调用模型')
    if status == 'completed' and len(items) != len(source_frames):
        status = 'material_limit'
    if status == 'completed':
        for frame, item, original in zip(derived.frames, items, source_frames):
            if (item.expected_sha256 != original['sha256']
                    or Path(item.path) != frame.image_path
                    or item.status not in {'recognized', 'no_text_detected'}):
                raise VideoEvidenceError('本次画面文字来源无法核验')
            # Do not replace independently retained OCR with an empty reading.
            if item.status == 'recognized':
                frame.ocr_text, frame.ocr_status = item.text, item.status
    if sum(len(frame.ocr_text or '') for frame in derived.frames) > _MAX_TEXT:
        # Revert the whole new reading, never keep an arbitrary partial prefix.
        derived = copy.deepcopy(evidence)
        derived._manifest_path = derived._manifest_payload = None
        status = 'material_limit'
    if sum(len(frame.ocr_text or '') for frame in derived.frames) > _MAX_TEXT:
        raise VideoEvidenceError('原有画面文字材料已超过输入预算，未调用模型')
    for frame, original in zip(evidence.frames, source_frames):
        if _frame_digest(frame.image_path) != original['sha256']:
            raise VideoEvidenceError('会议画面在文字分析期间发生变化')
    rows = []
    if status == 'completed':
        for item in items:
            row = asdict(item)
            row.pop('path')  # No OS locations in material receipts or prompts.
            rows.append(row)
    payload = {'protocol': 1, 'kind': 'desktop_derived_ocr',
        'owner': owner, 'task_id': task_id, 'status': status,
        'accepted_context_binding': context_binding,
        'capability': asdict(result.capability), 'failure': result.failure,
        'inputs_verified_after': result.inputs_verified_after,
        'source_frames': source_frames, 'source_revision': _hash(source_frames),
        'items': rows,
        'material_revision': _hash({'source_revision': _hash(source_frames),
            'accepted_context_binding': context_binding, 'frames': [{'sha256': original['sha256'],
            'ocr': frame.ocr_text, 'ocr_status': frame.ocr_status}
            for frame, original in zip(derived.frames, source_frames)]})}
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(raw) > _MAX_RECEIPT:
        raise VideoEvidenceError('本次画面文字材料超过预算，未调用模型')
    with destination.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    derived._summary_frame_hashes = {frame.image_path: row['sha256']
        for frame, row in zip(derived.frames, source_frames)}
    return derived
