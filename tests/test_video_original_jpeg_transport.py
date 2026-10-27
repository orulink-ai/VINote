"""Exact retained-JPEG transport only; synthetic fixtures, no provider/ASR/OCR."""
import base64
import copy
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import Mock

from PIL import Image
import pytest

from app.services import video_evidence_service as service, video_input_encoding as encoding
from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence, VideoEvidenceError
from test_video_input_transport import case, images


@pytest.mark.parametrize('proof', [None, False, True])
def test_even_verified_webp_sends_exact_original_without_conversion(tmp_path, monkeypatch, proof):
    evidence, source = case(tmp_path)
    before = evidence.text_material()
    monkeypatch.setattr(Image.Image, 'save', Mock(side_effect=AssertionError('No re-encode')))
    monkeypatch.setattr(Image.Image, 'convert', Mock(side_effect=AssertionError('No RGB conversion')))
    caps = {'vision': True, '_vinote_webp_verified': proof}
    first = evidence.user_content('draft', capabilities=caps)
    second = evidence.user_content('review', capabilities=caps)
    assert images(first) == images(second)
    assert evidence.text_material() == before
    receipt = evidence.input_receipt()
    assert receipt['requests_prepared'] == 2
    assert receipt['source_image_bytes'] == receipt['wire_image_bytes'] == 3 * len(source)
    for index, (url, row) in enumerate(zip(images(second), receipt['images'])):
        assert url.startswith('data:image/jpeg;base64,')
        assert base64.b64decode(url.split(',', 1)[1]) == source
        assert row['source_ref'] == f'[FRAME:{index + 1:04}]'
        assert row['offset_seconds'] == index * 35.5
        assert row['mime_type'] == 'image/jpeg' and row['policy'] == 'jpeg-original-v1'
        assert row['source_sha256'] == row['wire_sha256'] == hashlib.sha256(source).hexdigest()
        assert evidence.frames[index].image_path.read_bytes() == source


def test_retained_jpeg_metadata_is_not_stripped(tmp_path):
    evidence, source = case(tmp_path)
    payload = b'synthetic retained JPEG comment'
    source = source[:2] + b'\xff\xfe' + (len(payload) + 2).to_bytes(2, 'big') + payload + source[2:]
    for frame in evidence.frames:
        frame.image_path.write_bytes(source)
        evidence._summary_frame_hashes[frame.image_path] = hashlib.sha256(source).hexdigest()
    content = evidence.user_content('draft', capabilities={'vision': True, '_vinote_webp_verified': True})
    assert all(base64.b64decode(url.split(',', 1)[1]) == source for url in images(content))


@pytest.mark.parametrize('count', [61, 64])
def test_all_frame_identities_and_order_survive_without_dedup_or_resample(tmp_path, count):
    evidence, source = case(tmp_path)
    frame = evidence.frames[0]
    evidence.frames = [VideoFrameEvidence(count - i - .125, frame.image_path, ['timeline'],
        [count - i - .125, count - i], f'raw OCR {i}\n  spacing', 'recognized', [i], ['anonymous'])
        for i in range(count)]
    before = copy.deepcopy([(f.timestamp, f.sample_offsets, f.ocr_text, f.speech_indices, f.speaker_ids)
                            for f in evidence.frames])
    for phase in ('draft', 'review'):
        content = evidence.user_content(phase, capabilities={'vision': True, 'max_images': count,
                                                            '_vinote_webp_verified': True})
        assert len(images(content)) == count
        assert all(base64.b64decode(url.split(',', 1)[1]) == source for url in images(content))
        receipt = evidence.input_receipt()
        assert [r['source_ref'] for r in receipt['images']] == [f'[FRAME:{i + 1:04}]' for i in range(count)]
        assert [r['offset_seconds'] for r in receipt['images']] == [x[0] for x in before]
    assert before == [(f.timestamp, f.sample_offsets, f.ocr_text, f.speech_indices, f.speaker_ids)
                      for f in evidence.frames]
    assert evidence.input_receipt()['requests_prepared'] == 2


def test_changed_prepared_transport_metadata_still_rejects_before_replacing_receipt(tmp_path):
    evidence, source = case(tmp_path)
    evidence.user_content('draft', capabilities={'vision': True})
    before = evidence.input_receipt()
    key = (hashlib.sha256(source).hexdigest(), False)
    evidence._input_cache[key] = replace(evidence._input_cache[key], policy='changed-policy')
    with pytest.raises(VideoEvidenceError, match='版本已变化'):
        evidence.user_content('review', capabilities={'vision': True, '_vinote_webp_verified': True})
    assert evidence.input_receipt() == before


def test_prior_webp_cache_remains_intact_but_is_not_used_as_jpeg(tmp_path):
    evidence, source = case(tmp_path)
    key = (hashlib.sha256(source).hexdigest(), True)
    prior = encoding.encode_video_input(source, allow_webp=True)
    assert prior.mime_type == 'image/webp'
    evidence._input_cache[key] = prior
    content = evidence.user_content('new draft', capabilities={'vision': True, '_vinote_webp_verified': True})
    assert evidence._input_cache[key] is prior
    assert all(base64.b64decode(url.split(',', 1)[1]) == source for url in images(content))
    assert all(row['policy'] == 'jpeg-original-v1' for row in evidence.input_receipt()['images'])


def padded_jpeg(size):
    memory = io.BytesIO()
    Image.new('RGB', (16, 16), 'white').save(memory, 'JPEG')
    source = memory.getvalue()
    needed = size - len(source)
    comments = bytearray()
    while needed:
        total = min(needed, 65537)
        if 0 < needed - total < 4:
            total -= 4
        comments.extend(b'\xff\xfe' + (total - 2).to_bytes(2, 'big') + b'm' * (total - 4))
        needed -= total
    return source[:2] + comments + source[2:]


def budget_case(tmp_path, tail_size):
    first, last = tmp_path / 'full.jpg', tmp_path / 'tail.jpg'
    first.write_bytes(padded_jpeg(384 * 1024))
    last.write_bytes(padded_jpeg(tail_size))
    frames = [VideoFrameEvidence(i, first if i < 42 else last, ['timeline'], [i]) for i in range(43)]
    evidence = VideoEvidence(43, frames, 43, True)
    evidence._summary_frame_hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (first, last)}
    return evidence


def test_exact_original_aggregate_budget_allows_larger_base64_json_without_truncation(tmp_path):
    evidence = budget_case(tmp_path, 256 * 1024)
    content = evidence.user_content('draft', capabilities={'vision': True, '_vinote_webp_verified': True})
    receipt = evidence.input_receipt()
    assert receipt['source_image_bytes'] == receipt['wire_image_bytes'] == 16 * 1024 * 1024
    assert len(images(content)) == 43
    assert len(json.dumps([x for x in content if x['type'] == 'image_url'], separators=(',', ':')).encode()) > 16 * 1024 * 1024


def test_original_aggregate_budget_plus_one_rejects_before_encoding(tmp_path, monkeypatch):
    evidence = budget_case(tmp_path, 256 * 1024 + 1)
    guard = Mock(side_effect=AssertionError('Must reject before encoding'))
    monkeypatch.setattr(encoding, 'encode_video_input', guard)
    with pytest.raises(VideoEvidenceError, match='预算'):
        evidence.user_content('draft', capabilities={'vision': True, '_vinote_webp_verified': True})
    guard.assert_not_called()
    assert evidence.input_receipt() is None


def test_original_single_frame_budget_still_rejects_before_encoding(tmp_path, monkeypatch):
    evidence, _ = case(tmp_path)
    evidence.frames[0].image_path.write_bytes(b'x' * (384 * 1024 + 1))
    guard = Mock(side_effect=AssertionError('Must reject before encoding'))
    monkeypatch.setattr(encoding, 'encode_video_input', guard)
    with pytest.raises(VideoEvidenceError, match='预算'):
        evidence.user_content('draft', capabilities={'vision': True, '_vinote_webp_verified': True})
    guard.assert_not_called()
    assert evidence.input_receipt() is None
