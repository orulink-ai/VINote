"""Offline, real-Pillow boundaries; no model, OCR, media, file or network calls."""
import dataclasses
import hashlib
import io
import random
import socket

import pytest
from PIL import Image, ImageDraw, ImageFile

from app.services import video_input_encoding as encoding


def jpeg(image, **kwargs):
    output = io.BytesIO()
    image.save(output, format='JPEG', **kwargs)
    return output.getvalue()


@pytest.fixture(scope='module')
def text_and_diagram():
    image = Image.frombytes('RGB', (480, 270), random.Random(42).randbytes(480*270*3))
    draw = ImageDraw.Draw(image)
    draw.rectangle((15, 20, 460, 125), fill='white')
    draw.text((20, 25), 'A1 -> B2 | 24/25 | 12.50 | Name: Tester', fill='black')
    draw.rectangle((30, 65, 200, 110), outline='blue', width=2)
    draw.line((200, 85, 420, 85), fill='red', width=2)
    draw.polygon([(420, 85), (410, 81), (410, 89)], fill='red')
    return jpeg(image, quality=95, optimize=True)


def decoded(data):
    with Image.open(io.BytesIO(data)) as image:
        return image.convert('RGB').tobytes()


def assert_original(result, source):
    assert result.data is source
    assert result.mime_type == 'image/jpeg'
    assert result.policy == encoding.JPEG_POLICY
    assert result.source_sha256 == result.wire_sha256 == hashlib.sha256(source).hexdigest()
    assert result.size == len(source) <= encoding.MAX_INPUT_BYTES


def test_gate_false_never_converts_or_encodes(monkeypatch, text_and_diagram):
    def forbidden(*args, **kwargs):
        pytest.fail('false gate must not convert or encode')
    monkeypatch.setattr(Image.Image, 'save', forbidden)
    monkeypatch.setattr(Image.Image, 'convert', forbidden)
    result = encoding.encode_video_input(text_and_diagram, allow_webp=False)
    assert_original(result, text_and_diagram)
    assert (result.width, result.height) == (480, 270)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.size = 0


def test_real_webp_text_diagram_same_dimensions_loss_is_honest(text_and_diagram):
    before = bytes(bytearray(text_and_diagram))
    result = encoding.encode_video_input(text_and_diagram, allow_webp=True)
    assert result.mime_type == 'image/webp'
    assert result.policy == encoding.WEBP_POLICY
    assert result.size == len(result.data)
    assert result.size * 10 <= len(text_and_diagram) * 9
    assert result.size <= encoding.MAX_INPUT_BYTES
    assert (result.width, result.height) == (480, 270)
    assert result.source_sha256 == hashlib.sha256(text_and_diagram).hexdigest()
    assert result.wire_sha256 == hashlib.sha256(result.data).hexdigest()
    assert decoded(result.data) != decoded(text_and_diagram)  # No fidelity assertion.
    assert text_and_diagram == before
    with Image.open(io.BytesIO(result.data)) as image:
        assert image.format == 'WEBP' and image.size == (480, 270)


def test_policy_is_exactly_rgb_q80_method4(monkeypatch, text_and_diagram):
    calls = []
    real_save = Image.Image.save
    def spy(image, target, *args, **kwargs):
        calls.append((image.mode, image.size, dict(kwargs)))
        return real_save(image, target, *args, **kwargs)
    monkeypatch.setattr(Image.Image, 'save', spy)
    encoding.encode_video_input(text_and_diagram, allow_webp=True)
    assert len(calls) == 1
    mode, dimensions, kwargs = calls[0]
    assert (mode, dimensions) == ('RGB', (480, 270))
    assert kwargs == dict(format='WEBP', quality=80, method=4,
                          exif=b'', icc_profile=b'', xmp=b'')


@pytest.mark.parametrize('allow', [False, True])
def test_repeated_input_is_deterministic(text_and_diagram, allow):
    assert encoding.encode_video_input(text_and_diagram, allow_webp=allow) == encoding.encode_video_input(text_and_diagram, allow_webp=allow)


def test_unprofitable_real_webp_returns_exact_jpeg():
    image = Image.frombytes('RGB', (128, 96), random.Random(1).randbytes(128*96*3))
    source = jpeg(image, quality=5, optimize=True)
    result = encoding.encode_video_input(source, allow_webp=True)
    assert_original(result, source)


def test_ten_percent_boundary_uses_integer_bytes():
    image = Image.frombytes('RGB', (128, 96), random.Random(1).randbytes(128*96*3))
    source = jpeg(image, quality=5, optimize=True)
    output = io.BytesIO()
    with Image.open(io.BytesIO(source)) as im:
        im.convert('RGB').save(output, 'WEBP', quality=80, method=4)
    wire_size = len(output.getvalue())
    minimum_source = (wire_size * 10 + 8) // 9

    def padded(size):
        padding = size-len(source)
        assert 4 <= padding <= 65537
        comment = b'\xff\xfe'+(padding-2).to_bytes(2, 'big')+b'm'*(padding-4)
        return source[:2]+comment+source[2:]

    accepted = encoding.encode_video_input(padded(minimum_source), allow_webp=True)
    assert accepted.mime_type == 'image/webp' and accepted.size == wire_size
    below = padded(minimum_source-1)
    assert_original(encoding.encode_video_input(below, allow_webp=True), below)


def test_only_metadata_changes_source_hash_not_candidate_pixels(text_and_diagram):
    payload = b'comment including false marker \xff\xd9 and \xff\xda'
    comment = b'\xff\xfe'+(len(payload)+2).to_bytes(2, 'big')+payload
    source = text_and_diagram[:2]+comment+text_and_diagram[2:]
    original = encoding.encode_video_input(text_and_diagram, allow_webp=True)
    changed = encoding.encode_video_input(source, allow_webp=True)
    assert changed.source_sha256 != original.source_sha256
    assert changed.data == original.data
    assert changed.wire_sha256 == original.wire_sha256


def test_function_has_no_file_or_network_io(monkeypatch, text_and_diagram):
    def forbidden(*args, **kwargs):
        pytest.fail('encoding must use bytes only')
    monkeypatch.setattr('builtins.open', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    result = encoding.encode_video_input(text_and_diagram, allow_webp=True)
    assert result.mime_type == 'image/webp'


def test_metadata_is_in_source_hash_but_stripped_from_webp(text_and_diagram):
    with Image.open(io.BytesIO(text_and_diagram)) as image:
        exif = Image.Exif()
        exif[270] = 'synthetic source metadata'
        source = jpeg(image, quality=95, exif=exif, icc_profile=b'synthetic-icc')
    kept = encoding.encode_video_input(source, allow_webp=False)
    assert_original(kept, source)
    result = encoding.encode_video_input(source, allow_webp=True)
    assert result.mime_type == 'image/webp'
    assert result.source_sha256 == hashlib.sha256(source).hexdigest()
    assert result.source_sha256 != hashlib.sha256(text_and_diagram).hexdigest()
    with Image.open(io.BytesIO(result.data)) as image:
        assert not any(image.info.get(key) for key in ('exif', 'icc_profile', 'xmp'))


@pytest.mark.parametrize('mode', ['L', 'CMYK'])
def test_non_rgb_jpeg_decodes_to_rgb_without_geometry_change(mode):
    source = jpeg(Image.new(mode, (97, 61)), quality=95)
    result = encoding.encode_video_input(source, allow_webp=True)
    assert (result.width, result.height) == (97, 61)
    with Image.open(io.BytesIO(result.data)) as image:
        assert image.size == (97, 61)
        if result.mime_type == 'image/webp':
            assert image.mode == 'RGB'


def test_progressive_jpeg_input_is_complete(text_and_diagram):
    with Image.open(io.BytesIO(text_and_diagram)) as image:
        source = jpeg(image, progressive=True)
    assert_original(encoding.encode_video_input(source, allow_webp=False), source)


@pytest.mark.parametrize('allow', [None, 0, 1, 'true', [], {}])
def test_allow_webp_requires_actual_bool(text_and_diagram, allow):
    with pytest.raises(encoding.VideoInputEncodingError) as error:
        encoding.encode_video_input(text_and_diagram, allow_webp=allow)
    assert error.value.code is encoding.EncodingFailure.INVALID_PARAMETER


def test_gate_is_required(text_and_diagram):
    with pytest.raises(TypeError):
        encoding.encode_video_input(text_and_diagram)


@pytest.mark.parametrize('source', [None, 'jpeg', bytearray(b'jpeg'), memoryview(b'jpeg'), 1])
def test_input_requires_immutable_bytes(source):
    with pytest.raises(encoding.VideoInputEncodingError) as error:
        encoding.encode_video_input(source, allow_webp=False)
    assert error.value.code is encoding.EncodingFailure.INVALID_PARAMETER


@pytest.mark.parametrize('source', [b'', b'x'*(encoding.MAX_INPUT_BYTES+1)], ids=['empty', 'over-budget'])
def test_input_byte_budget_before_pillow(monkeypatch, source):
    monkeypatch.setattr(Image, 'open', lambda *a, **k: pytest.fail('must fail before decoding'))
    with pytest.raises(encoding.VideoInputEncodingError) as error:
        encoding.encode_video_input(source, allow_webp=True)
    assert error.value.code is encoding.EncodingFailure.INPUT_LIMIT


def test_exact_input_byte_limit_and_complete_metadata(text_and_diagram):
    # Valid COM segments pad a complete JPEG to the byte boundary, not trailing junk.
    needed = encoding.MAX_INPUT_BYTES - len(text_and_diagram)
    comments = bytearray()
    while needed:
        total = min(needed, 65537)
        if 0 < needed-total < 4:
            total -= 4
        comments.extend(b'\xff\xfe' + (total-2).to_bytes(2, 'big') + b'm'*(total-4))
        needed -= total
    source = text_and_diagram[:2] + bytes(comments) + text_and_diagram[2:]
    assert len(source) == encoding.MAX_INPUT_BYTES
    assert_original(encoding.encode_video_input(source, allow_webp=False), source)


@pytest.mark.parametrize('kind', ['PNG', 'WEBP', 'GIF'])
def test_valid_other_formats_are_not_jpeg(kind):
    buf = io.BytesIO()
    Image.new('RGB', (16, 16), 'white').save(buf, kind)
    with pytest.raises(encoding.VideoInputEncodingError) as error:
        encoding.encode_video_input(buf.getvalue(), allow_webp=True)
    assert error.value.code is encoding.EncodingFailure.INVALID_JPEG


@pytest.mark.parametrize('cut', [1, 2, 10, 100, 1000])
@pytest.mark.parametrize('allow', [False, True])
def test_truncated_jpeg_rejected_even_if_pillow_global_allows_truncation(monkeypatch, text_and_diagram, cut, allow):
    monkeypatch.setattr(ImageFile, 'LOAD_TRUNCATED_IMAGES', True)
    with pytest.raises(encoding.VideoInputEncodingError) as error:
        encoding.encode_video_input(text_and_diagram[:-cut], allow_webp=allow)
    assert error.value.code is encoding.EncodingFailure.INVALID_JPEG
    assert ImageFile.LOAD_TRUNCATED_IMAGES is True


@pytest.mark.parametrize('source', [b'\xff\xd8\xff\xd9', b'not-jpeg', b'\xff\xd8\xff\xe1\xff\xffx'])
def test_malformed_jpeg_is_typed(source):
    with pytest.raises(encoding.VideoInputEncodingError) as error:
        encoding.encode_video_input(source, allow_webp=False)
    assert error.value.code is encoding.EncodingFailure.INVALID_JPEG


def test_trailing_payload_is_not_accepted_as_jpeg(text_and_diagram):
    with pytest.raises(encoding.VideoInputEncodingError):
        encoding.encode_video_input(text_and_diagram+b'extra', allow_webp=False)


@pytest.mark.parametrize('size', [(1921, 10), (10, 1081), (1080, 1920)])
def test_each_dimension_limit_rejected_before_pillow(monkeypatch, size):
    source = jpeg(Image.new('RGB', size, 'white'))
    monkeypatch.setattr(Image, 'open', lambda *a, **k: pytest.fail('predecode dimension gate'))
    with pytest.raises(encoding.VideoInputEncodingError) as error:
        encoding.encode_video_input(source, allow_webp=False)
    assert error.value.code is encoding.EncodingFailure.IMAGE_LIMIT


def test_maximum_geometry_is_accepted():
    source = jpeg(Image.new('RGB', (1920, 1080), 'white'))
    result = encoding.encode_video_input(source, allow_webp=True)
    assert (result.width, result.height) == (1920, 1080)
    assert result.size <= len(source) <= encoding.MAX_INPUT_BYTES


def test_pixel_budget_is_independent(monkeypatch):
    source = jpeg(Image.new('RGB', (100, 100)))
    monkeypatch.setattr(encoding, 'MAX_DECODED_PIXELS', 9999)
    with pytest.raises(encoding.VideoInputEncodingError) as error:
        encoding.encode_video_input(source, allow_webp=False)
    assert error.value.code is encoding.EncodingFailure.IMAGE_LIMIT


def test_bomb_header_is_rejected_before_decode(monkeypatch, text_and_diagram):
    source = bytearray(text_and_diagram)
    pos = source.index(b'\xff\xc0')
    source[pos+5:pos+9] = b'\xff\xff\xff\xff'
    monkeypatch.setattr(Image, 'open', lambda *a, **k: pytest.fail('bomb must not decode'))
    with pytest.raises(encoding.VideoInputEncodingError) as error:
        encoding.encode_video_input(bytes(source), allow_webp=True)
    assert error.value.code is encoding.EncodingFailure.IMAGE_LIMIT


def test_candidate_output_is_bounded_and_cannot_be_truncated_into_success(monkeypatch, text_and_diagram):
    def huge_write(image, target, **kwargs):
        target.write(b'x'*(encoding.MAX_INPUT_BYTES+1))
    monkeypatch.setattr(Image.Image, 'save', huge_write)
    assert_original(encoding.encode_video_input(text_and_diagram, allow_webp=True), text_and_diagram)


@pytest.mark.parametrize('failure', [OSError('codec unavailable'), ValueError('bad codec'), KeyError('WEBP')])
def test_encoder_failure_is_typed_without_backend_message(monkeypatch, text_and_diagram, failure):
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(Image.Image, 'save', fail)
    with pytest.raises(encoding.VideoInputEncodingError) as error:
        encoding.encode_video_input(text_and_diagram, allow_webp=True)
    assert error.value.code is encoding.EncodingFailure.ENCODING_FAILED
    assert str(error.value) == 'encoding_failed'


def test_invalid_encoder_bytes_are_not_exposed_as_webp(monkeypatch, text_and_diagram):
    monkeypatch.setattr(Image.Image, 'save', lambda image, target, **kwargs: target.write(b'bad output'))
    with pytest.raises(encoding.VideoInputEncodingError) as error:
        encoding.encode_video_input(text_and_diagram, allow_webp=True)
    assert error.value.code is encoding.EncodingFailure.ENCODING_FAILED
