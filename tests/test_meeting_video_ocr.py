"""Offline derived-material contracts; no provider or transcription calls."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.services import meeting_video_ocr as service
from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence, VideoEvidenceError
from app.services.windows_ocr import OCRBatchResult, OCRCapability, OCRFailure, OCRItemResult


@pytest.fixture
def case(tmp_path, monkeypatch):
    donor, child = tmp_path / 'donor', tmp_path / 'child'
    donor.mkdir(); child.mkdir()
    image = donor / 'frame.jpg'
    image.write_bytes(b'input hash fixture, no real OCR invocation')
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    (donor / 'video_evidence.json').write_text('frozen donor')
    for name, value in [('generation_client', 'desktop'), ('.task_id', 'child'), ('recording_owner', 'alice')]:
        (child / name).write_text(value)
    evidence = VideoEvidence(10, [VideoFrameEvidence(2, image, ['timeline'], [2])], 10, True)
    evidence._manifest_path = donor / 'video_evidence.json'
    evidence._manifest_payload = {'frames': [{}]}
    evidence._summary_frame_hashes = {image: digest}
    result = OCRBatchResult('completed', OCRCapability('available', languages=('zh-Hans-CN',), actual_language='zh-Hans-CN'),
        (OCRItemResult(str(image), digest, 'recognized', text='真实截图 OCR 原文'),), inputs_verified_after=True)
    run = Mock(return_value=result)
    monkeypatch.setattr('app.services.windows_ocr.recognize_batch', run)
    monkeypatch.setattr(service, '_is_windows', lambda: True)
    def prepare():
        return service.prepare_meeting_video_ocr(evidence, task_dir=child, task_id='child', owner='alice',
            context_binding={'context_revision': 'revision', 'source_version': 'source', 'snapshot_sha256': 'model'})
    return locals()


def test_derived_material_preserves_donor_and_freezes_actual_revision(case):
    c = case
    result = c['prepare']()
    assert result.frames[0].ocr_text == '真实截图 OCR 原文'
    assert c['evidence'].frames[0].ocr_text is None
    assert (c['donor'] / 'video_evidence.json').read_text() == 'frozen donor'
    assert result._manifest_path is None and result._manifest_payload is None
    result.align([])
    assert (c['donor'] / 'video_evidence.json').read_text() == 'frozen donor'
    saved = json.loads((c['child'] / 'meeting_video_ocr.json').read_text(encoding='utf-8'))
    assert saved['task_id'] == 'child' and saved['owner'] == 'alice'
    assert saved['source_frames'][0]['sha256'] == c['digest']
    assert saved['items'][0]['text'] == '真实截图 OCR 原文'
    assert 'path' not in saved['items'][0]
    with pytest.raises(VideoEvidenceError, match='已有记录'):
        c['prepare']()
    assert c['run'].call_count == 1


@pytest.mark.parametrize('name,value', [('.task_id', 'other'), ('recording_owner', 'bob')])
def test_wrong_identity_never_ocr_or_writes(case, name, value):
    (case['child'] / name).write_text(value)
    with pytest.raises(VideoEvidenceError):
        case['prepare']()
    case['run'].assert_not_called()
    assert not (case['child'] / 'meeting_video_ocr.json').exists()


def test_changed_source_never_enters_provider_material(case):
    case['image'].write_bytes(b'changed')
    with pytest.raises(VideoEvidenceError, match='已变化'):
        case['prepare']()
    case['run'].assert_not_called()


def test_missing_frozen_frame_baseline_is_rejected(case):
    case['evidence']._summary_frame_hashes.clear()
    with pytest.raises(VideoEvidenceError, match='已变化'):
        case['prepare']()
    case['run'].assert_not_called()


def test_budget_checks_merged_existing_and_new_readings(case, monkeypatch):
    second = case['image'].with_name('other.jpg')
    second.write_bytes(b'other frozen image')
    digest = hashlib.sha256(second.read_bytes()).hexdigest()
    case['evidence'].frames[0].ocr_text = 'retained text'
    case['evidence'].frames[0].ocr_status = 'recognized'
    case['evidence'].frames.append(VideoFrameEvidence(4, second, ['timeline'], [4]))
    case['evidence']._summary_frame_hashes[second] = digest
    old = replace(case['result'].items[0], status='no_text_detected', text='')
    new = OCRItemResult(str(second), digest, 'recognized', text='new evidence')
    case['run'].return_value = replace(case['result'], items=(old, new))
    monkeypatch.setattr(service, '_MAX_TEXT', 15)
    result = case['prepare']()
    assert result.frames[0].ocr_text == 'retained text'
    assert result.frames[1].ocr_text is None
    assert json.loads((case['child'] / 'meeting_video_ocr.json').read_text())['status'] == 'material_limit'


def test_original_budget_exceeded_even_on_failed_ocr_is_rejected(case, monkeypatch):
    case['evidence'].frames[0].ocr_text = 'existing over budget'
    monkeypatch.setattr(service, '_MAX_TEXT', 3)
    case['run'].return_value = OCRBatchResult('failed', OCRCapability('unavailable'), failure=OCRFailure.BUSY)
    with pytest.raises(VideoEvidenceError, match='原有'):
        case['prepare']()


def test_changed_source_during_ocr_is_rejected(case):
    def changed(*args, **kwargs):
        case['image'].write_bytes(b'changed during OCR')
        return case['result']
    case['run'].side_effect = changed
    with pytest.raises(VideoEvidenceError, match='发生变化'):
        case['prepare']()
    assert not (case['child'] / 'meeting_video_ocr.json').exists()


def test_failed_batch_does_not_supply_partial_text(case):
    case['run'].return_value = OCRBatchResult('failed', OCRCapability('unavailable'),
        case['result'].items, OCRFailure.BATCH_TIMEOUT)
    result = case['prepare']()
    assert result.frames[0].ocr_text is None
    saved = json.loads((case['child'] / 'meeting_video_ocr.json').read_text())
    assert saved['items'] == [] and saved['status'] == 'failed'


def test_total_text_budget_does_not_truncate_into_evidence(case, monkeypatch):
    monkeypatch.setattr(service, '_MAX_TEXT', 3)
    result = case['prepare']()
    assert result.frames[0].ocr_text is None
    assert json.loads((case['child'] / 'meeting_video_ocr.json').read_text())['status'] == 'material_limit'


def test_mismatched_item_never_authorizes_ocr(case):
    case['run'].return_value = replace(case['result'], items=(replace(case['result'].items[0], expected_sha256='0'*64),))
    with pytest.raises(VideoEvidenceError, match='来源'):
        case['prepare']()
    assert not (case['child'] / 'meeting_video_ocr.json').exists()


def test_no_ocr_text_without_input_postcheck(case):
    case['run'].return_value = replace(case['result'], inputs_verified_after=False)
    with pytest.raises(VideoEvidenceError, match='后验'):
        case['prepare']()


@pytest.mark.parametrize('platform,client', [(False, 'desktop'), (True, 'cloud')])
def test_cloud_or_other_platform_has_no_native_process(case, monkeypatch, platform, client):
    monkeypatch.setattr(service, '_is_windows', lambda: platform)
    (case['child'] / 'generation_client').write_text(client)
    assert case['prepare']() is case['evidence']
    case['run'].assert_not_called()


def test_empty_reading_preserves_existing_ocr(case):
    case['evidence'].frames[0].ocr_text = 'already retained OCR'
    case['evidence'].frames[0].ocr_status = 'recognized'
    case['run'].return_value = replace(case['result'], items=(replace(case['result'].items[0], status='no_text_detected', text=''),))
    assert case['prepare']().frames[0].ocr_text == 'already retained OCR'
