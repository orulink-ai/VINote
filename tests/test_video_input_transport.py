import base64
import hashlib
import io
import json
from unittest.mock import Mock

from PIL import Image, ImageDraw
import pytest

from app.services.video_evidence_service import VideoEvidence, VideoFrameEvidence, VideoEvidenceError


def case(tmp_path):
    picture = Image.new('RGB', (1600, 900), 'white')
    draw = ImageDraw.Draw(picture)
    for n in range(35):
        draw.text((30, 20+n*24), f'Example source row {n}: 17.25, option A/B; pending.', fill='black')
    draw.rectangle((900, 200, 1200, 400), outline='blue', width=3)
    draw.line((1200, 300, 1450, 300), fill='black', width=3)
    raw = io.BytesIO()
    picture.save(raw, format='JPEG', quality=95)
    frames = []
    for index in range(3):
        path = tmp_path/f'{index}.jpg'
        path.write_bytes(raw.getvalue())
        frames.append(VideoFrameEvidence(index*35.5, path, ['timeline'], [index*35.5],
            f'Exact source OCR {index}\n  preserve spaces', 'recognized', [index], ['anonymous']))
    evidence = VideoEvidence(110, frames, 110, True)
    evidence._summary_frame_hashes = {f.image_path: hashlib.sha256(raw.getvalue()).hexdigest() for f in frames}
    return evidence, raw.getvalue()


def images(content):
    return [row['image_url']['url'] for row in content if row['type'] == 'image_url']


def test_original_jpeg_request_keeps_all_frames_timeline_ocr_and_originals(tmp_path):
    evidence, original = case(tmp_path)
    before = evidence.text_material()
    content = evidence.user_content('source task', capabilities={'vision': True, '_vinote_webp_verified': True})
    assert len(images(content)) == 3
    assert content[0]['text'] == 'source task\n\n' + before
    receipt = evidence.input_receipt()
    assert receipt['state'] == 'prepared' and receipt['requests_prepared'] == 1
    assert receipt['frame_count'] == 3 and receipt['mode'] == 'images'
    assert receipt['wire_image_bytes'] == receipt['source_image_bytes']
    for index, (image_url, row) in enumerate(zip(images(content), receipt['images'])):
        assert row['source_ref'] == f'[FRAME:{index+1:04}]'
        assert row['offset_seconds'] == index*35.5
        mime, encoded = image_url.split(';base64,')
        data = base64.b64decode(encoded)
        assert mime == 'data:image/jpeg' and row['mime_type'] == 'image/jpeg'
        assert row['policy'] == 'jpeg-original-v1'
        assert data == original
        assert row['source_sha256'] == hashlib.sha256(original).hexdigest()
        assert row['wire_sha256'] == hashlib.sha256(data).hexdigest()
        with Image.open(io.BytesIO(data)) as image:
            assert image.size == (1600, 900)
        assert evidence.frames[index].image_path.read_bytes() == original
    assert evidence.text_material() == before


def test_without_format_proof_jpegs_remain_byte_identical(tmp_path):
    evidence, original = case(tmp_path)
    content = evidence.user_content('source', capabilities={'vision': True})
    assert all(image.startswith('data:image/jpeg;base64,') for image in images(content))
    assert all(base64.b64decode(image.split(',')[1]) == original for image in images(content))
    assert all(row['source_sha256'] == row['wire_sha256'] for row in evidence.input_receipt()['images'])


def test_draft_and_review_use_identical_wire_images_and_cache(tmp_path, monkeypatch):
    from app.services import video_input_encoding
    evidence, _ = case(tmp_path)
    encode = Mock(wraps=video_input_encoding.encode_video_input)
    monkeypatch.setattr(video_input_encoding, 'encode_video_input', encode)
    caps = {'vision': True, '_vinote_webp_verified': True}
    first = evidence.user_content('draft', capabilities=caps)
    second = evidence.user_content('review', capabilities=caps)
    assert images(first) == images(second)
    assert evidence.input_receipt()['requests_prepared'] == 2
    # Identical input bytes share only encoding work, never timeline/source refs.
    assert encode.call_count == 1
    assert len(evidence.input_receipt()['images']) == 3


def test_changed_source_does_not_reuse_or_replace_prepared_evidence(tmp_path):
    evidence, _ = case(tmp_path)
    caps = {'vision': True, '_vinote_webp_verified': True}
    evidence.user_content('draft', capabilities=caps)
    before = evidence.input_receipt()
    picture = Image.new('RGB', (1600, 900), 'red')
    picture.save(evidence.frames[0].image_path, format='JPEG')
    with pytest.raises(VideoEvidenceError, match='变化'):
        evidence.user_content('review', capabilities=caps)
    assert evidence.input_receipt() == before


def test_optional_webp_proof_does_not_change_original_jpeg_review_images(tmp_path):
    evidence, _ = case(tmp_path)
    first = evidence.user_content('draft', capabilities={'vision': True})
    before = evidence.input_receipt()
    second = evidence.user_content('review', capabilities={'vision': True, '_vinote_webp_verified': True})
    assert images(first) == images(second)
    after = evidence.input_receipt()
    assert after['requests_prepared'] == 2
    assert {k: v for k, v in after.items() if k != 'requests_prepared'} == {
        k: v for k, v in before.items() if k != 'requests_prepared'}


def test_text_only_material_never_encodes_or_claims_images(tmp_path, monkeypatch):
    from app.services import video_input_encoding
    evidence, _ = case(tmp_path)
    monkeypatch.setattr(video_input_encoding, 'encode_video_input', Mock(side_effect=AssertionError('No images')))
    content = evidence.user_content('source', capabilities={'vision': False, '_vinote_webp_verified': True})
    assert isinstance(content, str) and 'No images were supplied' in content
    receipt = evidence.input_receipt()
    assert receipt['mode'] == 'ocr_only' and receipt['images'] == []
    assert receipt['state'] == 'prepared' and receipt['frame_count'] == 3


def test_unprepared_input_never_claims_model_submission(tmp_path):
    evidence, _ = case(tmp_path)
    assert evidence.input_receipt() is None


@pytest.mark.parametrize('first,second', [(True, False), (False, True)])
def test_draft_review_image_mode_cannot_change(tmp_path, first, second):
    evidence, _ = case(tmp_path)
    evidence.user_content('draft', capabilities={'vision': first})
    before = evidence.input_receipt()
    with pytest.raises(VideoEvidenceError, match='版本已变化'):
        evidence.user_content('review', capabilities={'vision': second})
    assert evidence.input_receipt() == before


@pytest.mark.parametrize('change', ['ocr', 'timestamp', 'references'])
def test_visual_source_text_does_not_change_between_stages(tmp_path, change):
    evidence, _ = case(tmp_path)
    evidence.user_content('draft', capabilities={'vision': True})
    before = evidence.input_receipt()
    if change == 'ocr': evidence.frames[0].ocr_text = 'different but equally valid source text'
    if change == 'timestamp': evidence.frames[0].timestamp += 1
    if change == 'references': evidence.frames[0].speech_indices.append(99)
    with pytest.raises(VideoEvidenceError, match='文字或时间线已变化'):
        evidence.user_content('review', capabilities={'vision': True})
    assert evidence.input_receipt() == before
