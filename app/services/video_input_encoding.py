"""Pure, bounded transport candidates for retained JPEG video evidence.

No file/network access, capability discovery, OCR, or source mutation. WebP is
lossy: successful encoding is neither readability nor model-quality acceptance.
RGB pixels keep their dimensions; EXIF orientation is not applied. Original JPEG
bytes (including metadata) remain the source identity. WebP carries no metadata.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import io
from typing import Literal

from PIL import Image, UnidentifiedImageError

MAX_INPUT_BYTES = 384 * 1024
MAX_WIDTH = 1920
MAX_HEIGHT = 1080
MAX_DECODED_PIXELS = MAX_WIDTH * MAX_HEIGHT
JPEG_POLICY = 'jpeg-original-v1'
WEBP_POLICY = 'webp-rgb-q80-method4-min10pct-v1'


class EncodingFailure(str, Enum):
    INVALID_PARAMETER = 'invalid_parameter'
    INPUT_LIMIT = 'input_limit'
    INVALID_JPEG = 'invalid_jpeg'
    IMAGE_LIMIT = 'image_limit'
    ENCODING_FAILED = 'encoding_failed'


class VideoInputEncodingError(ValueError):
    def __init__(self, code: EncodingFailure):
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class VideoInputEncodingResult:
    data: bytes
    mime_type: Literal['image/jpeg', 'image/webp']
    source_sha256: str
    wire_sha256: str
    width: int
    height: int
    policy: str
    size: int


def _fail(code: EncodingFailure):
    raise VideoInputEncodingError(code)


def _check_dimensions(width: int, height: int) -> None:
    if (not 0 < width <= MAX_WIDTH or not 0 < height <= MAX_HEIGHT
            or width * height > MAX_DECODED_PIXELS):
        _fail(EncodingFailure.IMAGE_LIMIT)


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Bound dimensions before Pillow and require complete marker/scan framing.

Length-delimited metadata is skipped as bytes, not interpreted as JPEG markers.
Entropy stuffing/restart markers and multiple progressive scans are supported.
Trailing payloads, missing EOI and truncated segments/scans are rejected.
"""
    if not data.startswith(b'\xff\xd8'):
        _fail(EncodingFailure.INVALID_JPEG)
    pos = 2
    dimensions = None
    scanned = False
    sof = {0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7,
           0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf}
    while pos < len(data):
        if data[pos] != 0xff:
            _fail(EncodingFailure.INVALID_JPEG)
        while pos < len(data) and data[pos] == 0xff:
            pos += 1
        if pos == len(data):
            _fail(EncodingFailure.INVALID_JPEG)
        marker = data[pos]
        pos += 1
        if marker == 0xd9:
            if pos != len(data) or dimensions is None or not scanned:
                _fail(EncodingFailure.INVALID_JPEG)
            return dimensions
        if marker in {0x00, 0xd8, *range(0xd0, 0xd8)}:
            _fail(EncodingFailure.INVALID_JPEG)
        if marker == 0x01:  # Standalone TEM, not a length-delimited segment.
            continue
        if pos + 2 > len(data):
            _fail(EncodingFailure.INVALID_JPEG)
        length = int.from_bytes(data[pos:pos + 2], 'big')
        end = pos + length
        if length < 2 or end > len(data):
            _fail(EncodingFailure.INVALID_JPEG)
        if marker in sof:
            if dimensions is not None or length < 8:
                _fail(EncodingFailure.INVALID_JPEG)
            height = int.from_bytes(data[pos + 3:pos + 5], 'big')
            width = int.from_bytes(data[pos + 5:pos + 7], 'big')
            _check_dimensions(width, height)
            dimensions = (width, height)
        pos = end
        if marker != 0xda:
            continue
        if dimensions is None or length < 6:
            _fail(EncodingFailure.INVALID_JPEG)
        scanned = True
        while True:
            next_marker = data.find(b'\xff', pos)
            if next_marker < 0:
                _fail(EncodingFailure.INVALID_JPEG)
            code = next_marker + 1
            while code < len(data) and data[code] == 0xff:
                code += 1
            if code == len(data):
                _fail(EncodingFailure.INVALID_JPEG)
            if data[code] == 0x00 or 0xd0 <= data[code] <= 0xd7:
                pos = code + 1
            else:
                pos = next_marker
                break
    _fail(EncodingFailure.INVALID_JPEG)


class _CandidateTooLarge(Exception):
    pass


class _BoundedBuffer(io.BytesIO):
    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit

    def write(self, data):
        if self.tell() + len(data) > self.limit:
            raise _CandidateTooLarge()
        return super().write(data)


def encode_video_input(data: bytes, *, allow_webp: bool) -> VideoInputEncodingResult:
    """Validate one JPEG; opt in to same-resolution RGB WebP Q80/method4.

Only a candidate at least 10% smaller is selected. Oversized/non-beneficial
candidate output returns the original JPEG; invalid input/codec failures are
typed errors. No selected output exceeds the bounded original input size.
Determinism is within the same Pillow/libwebp runtime, not across library versions.
"""
    if not isinstance(data, bytes) or type(allow_webp) is not bool:
        _fail(EncodingFailure.INVALID_PARAMETER)
    if not 0 < len(data) <= MAX_INPUT_BYTES:
        _fail(EncodingFailure.INPUT_LIMIT)
    width, height = _jpeg_dimensions(data)
    source_hash = hashlib.sha256(data).hexdigest()

    def original():
        return VideoInputEncodingResult(data, 'image/jpeg', source_hash,
                                        source_hash, width, height, JPEG_POLICY, len(data))

    try:
        with Image.open(io.BytesIO(data), formats=['JPEG']) as image:
            if image.format != 'JPEG' or image.size != (width, height):
                _fail(EncodingFailure.INVALID_JPEG)
            image.verify()
        with Image.open(io.BytesIO(data), formats=['JPEG']) as image:
            image.load()  # verify() alone does not decode JPEG scan data.
            if not allow_webp:
                return original()
            rgb = image.convert('RGB')
    except Image.DecompressionBombError:
        raise VideoInputEncodingError(EncodingFailure.IMAGE_LIMIT) from None
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError):
        raise VideoInputEncodingError(EncodingFailure.INVALID_JPEG) from None

    rgb.info.clear()
    try:
        with _BoundedBuffer(len(data) * 9 // 10) as output:
            try:
                rgb.save(output, format='WEBP', quality=80, method=4,
                         exif=b'', icc_profile=b'', xmp=b'')
            except _CandidateTooLarge:
                return original()
            encoded = output.getvalue()
        if not encoded or len(encoded) * 10 > len(data) * 9:
            _fail(EncodingFailure.ENCODING_FAILED)
        with Image.open(io.BytesIO(encoded), formats=['WEBP']) as candidate:
            if (candidate.format != 'WEBP' or candidate.size != (width, height)
                    or candidate.mode != 'RGB'
                    or any(candidate.info.get(key) for key in ('exif', 'icc_profile', 'xmp'))):
                _fail(EncodingFailure.ENCODING_FAILED)
            candidate.load()
    except (OSError, ValueError, SyntaxError, KeyError, UnidentifiedImageError):
        raise VideoInputEncodingError(EncodingFailure.ENCODING_FAILED) from None
    finally:
        rgb.close()
    return VideoInputEncodingResult(encoded, 'image/webp', source_hash,
                                    hashlib.sha256(encoded).hexdigest(), width, height,
                                    WEBP_POLICY, len(encoded))
