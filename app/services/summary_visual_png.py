"""Bounded, offline Pillow rendering of an already authorized summary-visual/1.

The caller must verify owner/task/body/accepted receipt and screenshot hashes.
This module accepts bytes, never paths or URLs, and does not write files or DBs.
Only the fixed bundled font is read. No SVG, HTML, inference or network exists.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass, is_dataclass
from decimal import Decimal
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import re
import struct
import sys
from types import CodeType, FunctionType, ModuleType
from typing import Literal, Mapping, TypedDict
import unicodedata
import warnings
import zlib

import PIL
from PIL import Image, ImageDraw, ImageFont, features


class VisualBlock(TypedDict):
    id: str
    text: str
    claim_ids: list[str]


class VisualFrame(TypedDict):
    id: str
    screenshot_index: int
    timestamp_seconds: float
    grounded_label: str


class VisualScene(TypedDict):
    id: str
    block_ids: list[str]
    frame_id: str
    grounded_label: str


class VisualNode(TypedDict):
    id: str
    block_ids: list[str]
    grounded_label: str


VisualEdge = TypedDict('VisualEdge', {
    'id': str, 'from': str, 'to': str, 'block_ids': list[str], 'grounded_label': str,
})


class VisualDiagram(TypedDict):
    kind: Literal['cards', 'comparison', 'flow', 'relationship']
    nodes: list[VisualNode]
    edges: list[VisualEdge]


class SummaryVisual(TypedDict):
    visual_protocol: Literal[1]
    task_id: str
    presentation: Literal['comic', 'infographic']
    body_sha256: str
    blocks: list[VisualBlock]
    frames: list[VisualFrame]
    scenes: list[VisualScene]
    diagram: VisualDiagram | None


PROTOCOL = 'summary-visual-png/1'
RENDERER_VERSION = '1.0.0'
FONT_SHA256 = '028a6826552d2ab32eede9d4243381351382a154f974d96cac543fc571570407'
_FONT_PATH = Path(__file__).resolve().parents[1] / 'resources/fonts/NotoSansSC-Regular.ttf'
_ID = re.compile(r'[A-Za-z0-9_\[\]:.\-]{1,64}\Z')
_TASK = re.compile(r'[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}\Z')
_MARGIN = 48
_FOREGROUND = '#18181b'
_MUTED = '#52525b'
_BORDER = '#d4d4d8'
_ACCENT = '#f4f4f5'
_EDGE_COLORS = ('#1d4ed8', '#7c3aed', '#0f766e', '#9f1239', '#92400e')


class SummaryVisualPngError(ValueError):
    def __init__(self, code: str, message: str = '图形无法完整导出，正文和原图保留。'):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RenderLimits:
    page_width: int = 1440
    page_height: int = 4096
    max_pages: int = 16
    max_page_bytes: int = 20 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024
    max_page_pixels: int = 8_000_000
    max_total_pixels: int = 96_000_000
    max_frame_bytes: int = 2 * 1024 * 1024
    max_total_frame_bytes: int = 16 * 1024 * 1024
    max_frame_pixels: int = 4096 * 4096


DEFAULT_LIMITS = RenderLimits()


@dataclass(frozen=True)
class SemanticItem:
    kind: Literal['scene', 'node', 'edge']
    id: str
    text: str
    block_ids: tuple[str, ...]
    frame_id: str | None = None
    timestamp_seconds: float | None = None
    from_id: str | None = None
    to_id: str | None = None

    @property
    def ref(self) -> str:
        return f'{self.kind}:{self.id}'


@dataclass(frozen=True)
class TextRun:
    text: str
    x: int
    y: int
    width: int
    height: int
    font_size: int
    semantic_ref: str | None = None


@dataclass(frozen=True)
class EdgeRoute:
    id: str
    from_id: str
    to_id: str
    points: tuple[tuple[int, int], ...]
    arrow: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class PngPage:
    png_bytes: bytes
    width: int
    height: int
    sha256: str
    semantic_refs: tuple[str, ...]
    text_runs: tuple[TextRun, ...] = ()
    edge_routes: tuple[EdgeRoute, ...] = ()


@dataclass(frozen=True)
class PngRenderResult:
    pages: tuple[PngPage, ...]
    semantic_order: tuple[SemanticItem, ...]
    identity_items: tuple[tuple[str, str], ...]
    fingerprint: str

    @property
    def renderer_identity(self) -> dict[str, str]:
        return dict(self.identity_items)


def _need(condition, code='invalid_visual'):
    if not condition:
        raise SummaryVisualPngError(code)


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


@lru_cache(maxsize=1)
def _font_bytes() -> bytes:
    try:
        _need(not _FONT_PATH.is_symlink(), 'font_unavailable')
        with _FONT_PATH.open('rb') as stream:
            data = stream.read(16 * 1024 * 1024 + 1)
        _need(sha256(data).hexdigest() == FONT_SHA256, 'font_hash_mismatch')
        return data
    except OSError:
        raise SummaryVisualPngError('font_unavailable', '固定中文字体不可用，未替换系统字体。') from None


@lru_cache(maxsize=8)
def _font(size: int):
    return ImageFont.truetype(BytesIO(_font_bytes()), size, layout_engine=ImageFont.Layout.BASIC)


@lru_cache(maxsize=1)
def _coverage():
    """Read the fixed font's Unicode cmap; absent glyphs must not become tofu."""
    data = _font_bytes()
    count = struct.unpack_from('>H', data, 4)[0]
    cmap = next(struct.unpack_from('>I', data, 12 + 16 * i + 8)[0]
                for i in range(count) if data[12 + 16 * i:16 + 16 * i] == b'cmap')
    tables = struct.unpack_from('>H', data, cmap + 2)[0]
    ranges = []
    for i in range(tables):
        platform, encoding, offset = struct.unpack_from('>HHI', data, cmap + 4 + 8 * i)
        position = cmap + offset
        if platform not in (0, 3) or (platform == 3 and encoding not in (1, 10)):
            continue
        if struct.unpack_from('>H', data, position)[0] != 12:
            continue
        groups = struct.unpack_from('>I', data, position + 12)[0]
        for j in range(groups):
            start, end, glyph = struct.unpack_from('>III', data, position + 16 + 12 * j)
            ranges.append((start + (glyph == 0), end))
    _need(bool(ranges), 'font_cmap_unavailable')
    # The pinned font contains a complete format-12 Unicode cmap. Merge its
    # duplicate platform records so binary search cannot hide a supported range.
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(start for start, _ in merged), tuple(end for _, end in merged)


def _glyphs(text):
    starts, ends = _coverage()
    for char in text:
        if char == '\n':
            continue
        value = ord(char)
        index = bisect_right(starts, value) - 1
        _need(index >= 0 and value <= ends[index], 'unsupported_glyph')


def renderer_identity() -> dict[str, str]:
    """Verify bundled font bytes; no caller paths, system fonts or file writes."""
    _font_bytes()
    value = dict(protocol=PROTOCOL, renderer_version=RENDERER_VERSION, font_sha256=FONT_SHA256,
                 pillow_version=PIL.__version__, freetype_version=features.version('freetype2') or '',
                 layout_engine='Pillow BASIC', zlib_runtime=zlib.ZLIB_RUNTIME_VERSION,
                 python_implementation=sys.implementation.name,
                 python_version='.'.join(map(str, sys.version_info[:3])),
                 python_cache_tag=sys.implementation.cache_tag or '',
                 python_optimize=str(sys.flags.optimize), python_byteorder=sys.byteorder,
                 implementation_schema='loaded-local-python/1',
                 implementation_sha256=_implementation_digest())
    return {**value, 'fingerprint': sha256(_json(value)).hexdigest()}


def _identity_value(value):
    """Canonical immutable values, independent of paths, object IDs/hash seeds."""
    if isinstance(value, CodeType):
        # Compare loaded executable code, not source/pyc/loader rereads. Location
        # tables are deliberately excluded: source and PYZ rewrite filenames.
        fields = ('co_code', 'co_exceptiontable', 'co_consts', 'co_names', 'co_varnames',
                  'co_freevars', 'co_cellvars', 'co_argcount', 'co_posonlyargcount',
                  'co_kwonlyargcount', 'co_nlocals', 'co_stacksize', 'co_flags')
        return ['code', {key: _identity_value(getattr(value, key)) for key in fields}]
    if value is None or type(value) in (bool, int, str):
        return [type(value).__name__, value]
    if value is Ellipsis:
        return ['ellipsis']
    if type(value) is float:
        return ['float', value.hex()]
    if type(value) is bytes:
        return ['bytes', value.hex()]
    if type(value) in (tuple, frozenset):
        rows = [_identity_value(item) for item in value]
        return [type(value).__name__, sorted(rows, key=_json) if type(value) is frozenset else rows]
    if isinstance(value, re.Pattern):
        return ['regex', value.pattern, value.flags]
    if is_dataclass(value) and not isinstance(value, type) and value.__dataclass_params__.frozen:
        return ['frozen-dataclass', type(value).__name__,
                {key: _identity_value(item) for key, item in asdict(value).items()}]
    raise SummaryVisualPngError('implementation_binding_unavailable')


def _identity_callable(value):
    if isinstance(value, (staticmethod, classmethod)):
        value = value.__func__
    if isinstance(value, property):
        return ['property', [_identity_callable(item) if item else None
                             for item in (value.fget, value.fset, value.fdel)]]
    if isinstance(value, FunctionType):
        result = ['function', _identity_value(value.__code__), _identity_value(value.__defaults__),
                  {key: _identity_value(item) for key, item in (value.__kwdefaults__ or {}).items()}]
        captured = {}
        for name, cell in zip(value.__code__.co_freevars, value.__closure__ or ()):
            item = cell.cell_contents
            if isinstance(item, FunctionType):
                captured[name] = _identity_callable(item)
            elif isinstance(item, type):
                captured[name] = ['class', item.__module__, item.__qualname__]
            elif name == 'repr_running' and type(item) is set and hasattr(value, '__wrapped__'):
                captured[name] = ['dataclass-repr-recursion-cache']
            else:
                captured[name] = _identity_value(item)
        result.append(captured)
        if hasattr(value, '__wrapped__'):
            result.append(_identity_callable(value.__wrapped__))
        return result
    # functools' C lru wrapper has no Python code. Bind its live wrapped code
    # and parameters, never the mutable cache contents or its object address.
    if hasattr(value, '__wrapped__') and hasattr(value, 'cache_parameters'):
        return ['lru-cache', value.cache_parameters(), _identity_callable(value.__wrapped__)]
    raise SummaryVisualPngError('implementation_binding_unavailable')


def _implementation_digest():
    """Local Python implementation/config only; native engines are version-bound.

    No claim of hashing all transitive native libraries. Import-time name lists
    keep subsequent replacement functions bound even if defined in another
    module. Read the CURRENT bindings at each preflight; do not cache this hash.
    """
    namespace = globals().copy()
    functions = {name: _identity_callable(namespace[name]) for name in _IDENTITY_FUNCTION_NAMES}
    classes = {}
    for name in _IDENTITY_CLASS_NAMES:
        members = {}
        for key, value in vars(namespace[name]).items():
            if isinstance(value, (FunctionType, staticmethod, classmethod, property)):
                members[key] = _identity_callable(value)
            elif not key.startswith('__') and type(value) in (bool, int, float, str, bytes, tuple, frozenset):
                members[key] = _identity_value(value)
        classes[name] = members
    # The path is a deployment locator, not rendering input; exact font bytes
    # are independently pinned/verified. All other uppercase bindings must be
    # canonical immutable values, including palette, regexes and default limits.
    constants = {name: _identity_value(value) for name, value in namespace.items()
                 if name.isupper() and name != '_FONT_PATH' and not isinstance(value, (ModuleType, type))}
    return sha256(_json(dict(functions=functions, classes=classes, constants=constants))).hexdigest()


def _check_limits(limits):
    _need(type(limits) is RenderLimits, 'invalid_limits')
    for key, value in asdict(limits).items():
        ceiling = 2048 if key == 'page_width' else getattr(DEFAULT_LIMITS, key)
        _need(type(value) is int and 0 < value <= ceiling, 'invalid_limits')
    _need(limits.page_width >= 960 and limits.page_height >= 640, 'invalid_limits')
    _need(limits.page_width * limits.page_height <= limits.max_page_pixels, 'pixel_budget')


def _object(value, keys):
    _need(type(value) is dict and set(value) == set(keys))


def _rows(value, maximum, minimum=0):
    _need(type(value) is list and minimum <= len(value) <= maximum)


def _id(value):
    _need(isinstance(value, str) and _ID.fullmatch(value) is not None)


def _label(value):
    _need(isinstance(value, str) and bool(value.strip()) and len(value) <= 120
          and not re.search(r'[\x00-\x1f\x7f]', value))
    _glyphs(value)


def _validate(visual, title):
    """Defense in depth only; this does not establish owner/body authorization."""
    _object(visual, ('visual_protocol', 'task_id', 'presentation', 'body_sha256',
                     'blocks', 'frames', 'scenes', 'diagram'))
    _need(type(visual['visual_protocol']) is int and visual['visual_protocol'] == 1)
    _need(isinstance(visual['task_id'], str) and _TASK.fullmatch(visual['task_id']) is not None)
    _need(visual['presentation'] in ('comic', 'infographic'))
    _need(isinstance(visual['body_sha256'], str) and re.fullmatch(r'[a-f0-9]{64}', visual['body_sha256']))
    _need(isinstance(title, str) and len(title) <= 500 and not re.search(r'[\x00-\x09\x0b-\x1f\x7f]', title))
    _glyphs(title)
    _rows(visual['blocks'], 64, 1)
    blocks = {}
    for block in visual['blocks']:
        _object(block, ('id', 'text', 'claim_ids'))
        _id(block['id'])
        _need(block['id'] not in blocks and isinstance(block['text'], str)
              and bool(block['text'].strip()) and len(block['text']) <= 6000)
        _rows(block['claim_ids'], 64)
        for claim in block['claim_ids']:
            _id(claim)
        _need(len(set(block['claim_ids'])) == len(block['claim_ids']))
        blocks[block['id']] = block

    def referenced(row):
        _id(row['id'])
        _label(row['grounded_label'])
        _rows(row['block_ids'], 8, 1)
        for key in row['block_ids']:
            _id(key)
            _need(key in blocks)
        _need(len(set(row['block_ids'])) == len(row['block_ids'])
              and any(blocks[key]['claim_ids'] for key in row['block_ids'])
              and any(row['grounded_label'] in blocks[key]['text'] for key in row['block_ids']))

    _rows(visual['frames'], 8)
    frames, indices = {}, set()
    for frame in visual['frames']:
        _object(frame, ('id', 'screenshot_index', 'timestamp_seconds', 'grounded_label'))
        _id(frame['id'])
        _label(frame['grounded_label'])
        stamp, index = frame['timestamp_seconds'], frame['screenshot_index']
        try:
            finite = type(stamp) in (int, float) and math.isfinite(stamp) and stamp >= 0
        except OverflowError:
            finite = False
        _need(finite and frame['id'] not in frames and type(index) is int and 0 <= index <= 7 and index not in indices)
        frames[frame['id']] = frame
        indices.add(index)
    _rows(visual['scenes'], 8)
    seen, used_frames = set(), set()
    for scene in visual['scenes']:
        _object(scene, ('id', 'block_ids', 'frame_id', 'grounded_label'))
        referenced(scene)
        _need(scene['id'] not in seen and isinstance(scene['frame_id'], str) and scene['frame_id'] in frames)
        seen.add(scene['id'])
        used_frames.add(scene['frame_id'])
    if visual['presentation'] == 'comic':
        _need(bool(seen) and used_frames == set(frames) and visual['diagram'] is None)
    else:
        _need(not seen)
        diagram = visual['diagram']
        _object(diagram, ('kind', 'nodes', 'edges'))
        _need(diagram['kind'] in ('cards', 'comparison', 'flow', 'relationship'))
        _rows(diagram['nodes'], 12, 1)
        _rows(diagram['edges'], 20)
        nodes, edges = set(), set()
        for node in diagram['nodes']:
            _object(node, ('id', 'block_ids', 'grounded_label'))
            referenced(node)
            _need(node['id'] not in nodes)
            nodes.add(node['id'])
        for edge in diagram['edges']:
            _object(edge, ('id', 'from', 'to', 'block_ids', 'grounded_label'))
            referenced(edge)
            _need(edge['id'] not in edges and isinstance(edge['from'], str) and edge['from'] in nodes
                  and isinstance(edge['to'], str) and edge['to'] in nodes)
            edges.add(edge['id'])
        _need(diagram['kind'] not in ('cards', 'comparison') or not edges)
    _need(len(_json(visual)) <= 128 * 1024, 'visual_byte_budget')
    return json.loads(_json(visual))  # Detached, bounded data; input is never mutated.


def _frames(visual, frame_bytes, limits):
    _need(isinstance(frame_bytes, Mapping), 'invalid_frame_bytes')
    _need(len(frame_bytes) <= 8, 'frame_set_mismatch')
    _need(set(frame_bytes) == {frame['id'] for frame in visual['frames']}, 'frame_set_mismatch')
    _need(all(type(value) is bytes and 0 < len(value) <= limits.max_frame_bytes for value in frame_bytes.values()),
          'frame_byte_budget')
    _need(sum(map(len, frame_bytes.values())) <= limits.max_total_frame_bytes, 'frame_byte_budget')
    result = {}
    for key, data in frame_bytes.items():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as image:
                    _need(image.format in ('PNG', 'JPEG') and getattr(image, 'n_frames', 1) == 1, 'frame_format')
                    width, height = image.size
                    _need(0 < width <= 4096 and 0 < height <= 4096 and width * height <= limits.max_frame_pixels,
                          'frame_pixel_budget')
                    image.load()
            result[key] = data
        except (OSError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
            raise SummaryVisualPngError('invalid_frame_bytes') from None
    return result


def _width(text, font):
    box = font.getbbox(text)
    return max(font.getlength(text), box[2] - box[0])


def _lines(text, width, size):
    font = _font(size)
    # Keep combining marks on their base glyph; never ellipsize, strip or split
    # away punctuation/conditions. ASCII identifiers stay whole when they fit.
    tokens = re.findall(r'[A-Za-z0-9]+(?:[.:/%–-][A-Za-z0-9]+)*|[^\n][\u0300-\u036f]*|\n', text)
    joined = []
    for token in tokens:
        if joined and token != '\n' and unicodedata.combining(token[0]):
            joined[-1] += token
        else:
            joined.append(token)
    output, line = [], ''
    for token in joined:
        if token == '\n':
            output.append(line)
            line = ''
        elif _width(token, font) <= width:
            if line and _width(line + token, font) > width:
                output.append(line)
                line = ''
            line += token
        else:
            clusters = []
            for char in token:
                if clusters and unicodedata.combining(char):
                    clusters[-1] += char
                else:
                    clusters.append(char)
            for cluster in clusters:
                _need(_width(cluster, font) <= width, 'text_layout_budget')
                if line and _width(line + cluster, font) > width:
                    output.append(line)
                    line = ''
                line += cluster
    output.append(line)
    # Avoid a one-character final line. Prefer a literal punctuation/space
    # boundary immediately before it (e.g. keep the last listed name together),
    # without guessing words, deleting punctuation or crossing explicit breaks.
    if '\n' not in text and len(output) >= 2 and output[-1] and _width(output[-1], font) < size * 1.5:
        previous = output[-2]
        if previous and previous[-1] != '\n':
            boundaries = [i + 1 for i, char in enumerate(previous)
                          if char in '、，；：,;: ' and 0 < len(previous) - i - 1 <= 8]
            split = boundaries[-1] if boundaries else len(previous) - 1
            if (split > 0 and previous[split:] and not unicodedata.combining(previous[split])
                    and _width(previous[split:] + output[-1], font) <= width):
                output[-2], output[-1] = previous[:split], previous[split:] + output[-1]
    return output


def _timestamp(seconds):
    integer, _, fraction = format(Decimal(str(seconds)), 'f').partition('.')
    hours, rem = divmod(int(integer), 3600)
    minutes, sec = divmod(rem, 60)
    suffix = fraction.rstrip('0')
    return f'{hours:02d}:{minutes:02d}:{sec:02d}' + ('.' + suffix if suffix else '')


class _BoundedBuffer(BytesIO):
    def __init__(self, limit):
        super().__init__()
        self.limit = limit

    def write(self, data):
        _need(self.tell() + len(data) <= self.limit, 'png_byte_budget')
        return super().write(data)


class _Document:
    def __init__(self, limits, label, semantics):
        self.limits, self.label = limits, label
        self.order = {item.ref: index for index, item in enumerate(semantics)}
        self.pages = []
        self.image = None
        self.total_bytes = self.total_pixels = 0
        self.y = 0

    @property
    def bottom(self):
        return self.limits.page_height - 88

    def new_page(self):
        self.seal()
        _need(len(self.pages) < self.limits.max_pages, 'page_budget')
        self.image = Image.new('RGB', (self.limits.page_width, self.limits.page_height), 'white')
        self.draw = ImageDraw.Draw(self.image)
        self.refs, self.runs, self.routes = set(), [], []
        self.line(self.label, _MARGIN, 30, 24, color=_MUTED)
        self.y = 94

    def ensure(self, height):
        _need(height <= self.bottom - 94, 'page_layout_budget')
        if self.image is None or self.y + height > self.bottom:
            self.new_page()

    def line(self, text, x, y, size, *, ref=None, color=_FOREGROUND):
        font = _font(size)
        left, top, right, bottom = font.getbbox(text)
        w, h = right - left, bottom - top
        _need(0 <= x <= self.limits.page_width - w and 0 <= y <= self.limits.page_height - h,
              'text_layout_budget')
        self.draw.text((x - left, y - top), text, fill=color, font=font)
        self.runs.append(TextRun(text, int(x), int(y), w, h, size, ref))
        if ref:
            self.refs.add(ref)

    def text(self, text, *, ref=None, size=30, gap=18, keep_together=False):
        lines = _lines(text, self.limits.page_width - 2 * _MARGIN, size)
        height = len(lines) * (size + 14) + gap
        if keep_together and height <= self.bottom - 94:
            self.ensure(height)
        for line in lines:
            self.ensure(size + 18)
            self.line(line, _MARGIN, self.y, size, ref=ref)
            self.y += size + 14
        self.y += gap

    def seal(self):
        if self.image is None:
            return
        height = min(self.limits.page_height, max(240, self.y + 78))
        self.line(f'页 {len(self.pages) + 1}', _MARGIN, height - 42, 22, color=_MUTED)
        pixels = self.limits.page_width * height
        _need(pixels <= self.limits.max_page_pixels and self.total_pixels + pixels <= self.limits.max_total_pixels,
              'pixel_budget')
        with _BoundedBuffer(min(self.limits.max_page_bytes, self.limits.max_total_bytes - self.total_bytes)) as stream:
            self.image.crop((0, 0, self.limits.page_width, height)).save(stream, 'PNG', compress_level=6)
            data = stream.getvalue()
        self.pages.append(PngPage(data, self.limits.page_width, height, sha256(data).hexdigest(),
            tuple(sorted(self.refs, key=self.order.__getitem__)), tuple(self.runs), tuple(self.routes)))
        self.total_bytes += len(data)
        self.total_pixels += pixels
        self.image.close()
        self.image = None

    def close(self):
        if self.image is not None:
            self.image.close()
            self.image = None


def _comic(doc, visual, frames):
    by_id = {frame['id']: frame for frame in visual['frames']}
    width = doc.limits.page_width - 2 * _MARGIN
    for number, scene in enumerate(visual['scenes'], 1):
        frame = by_id[scene['frame_id']]
        ref = f"scene:{scene['id']}"
        caption = _lines(scene['grounded_label'], width - 48, 30)
        stamp = _lines(f'{number:02d} · {_timestamp(frame["timestamp_seconds"])}', width - 48, 26)
        with Image.open(BytesIO(frames[frame['id']])) as source:
            # Contain the complete real frame; no crop, illustration or fill-in.
            image_height = min(1000, doc.bottom - 94 - 120 - 44 * len(caption) - 40 * len(stamp))
            _need(image_height >= 96, 'page_layout_budget')
            scale = min((width - 2) / source.width, image_height / source.height)
            size = (max(1, int(source.width * scale)), max(1, int(source.height * scale)))
            height = size[1] + 76 + len(stamp) * 40 + len(caption) * 44
            doc.ensure(height + 24)
            y = doc.y
            doc.draw.rounded_rectangle((_MARGIN, y, _MARGIN + width, y + height), radius=14,
                                       fill='white', outline=_BORDER, width=2)
            if source.mode in ('RGBA', 'LA') or 'transparency' in source.info:
                rgba = source.convert('RGBA')
                rgb = Image.new('RGB', source.size, 'white')
                rgb.paste(rgba, mask=rgba.getchannel('A'))
                rgba.close()
            else:
                rgb = source.convert('RGB')
            picture = rgb.resize(size, Image.Resampling.LANCZOS)
            doc.image.paste(picture, (_MARGIN + (width - size[0]) // 2, y + 16))
            picture.close()
            rgb.close()
        doc.y = y + size[1] + 32
        for line in stamp:
            doc.line(line, _MARGIN + 24, doc.y, 26, ref=ref, color=_MUTED)
            doc.y += 40
        for line in caption:
            doc.line(line, _MARGIN + 24, doc.y, 30, ref=ref)
            doc.y += 44
        doc.y = y + height + 24


def _cards(doc, diagram):
    gap = 28
    width = (doc.limits.page_width - 2 * _MARGIN - gap) // 2
    nodes = diagram['nodes']
    for offset in range(0, len(nodes), 2):
        row = nodes[offset:offset + 2]
        lines = [_lines(node['grounded_label'], width - 48, 30) for node in row]
        height = max(len(value) for value in lines) * 44 + 84
        doc.ensure(height + 24)
        y = doc.y
        for column, (node, value) in enumerate(zip(row, lines)):
            x = _MARGIN + column * (width + gap)
            ref = f"node:{node['id']}"
            doc.draw.rounded_rectangle((x, y, x + width, y + height), radius=14,
                                       fill=_ACCENT, outline=_BORDER, width=2)
            doc.line(f'{offset + column + 1:02d}', x + 24, y + 18, 24, ref=ref, color=_MUTED)
            for index, line in enumerate(value):
                doc.line(line, x + 24, y + 58 + index * 44, 30, ref=ref)
        doc.y += height + 24


def _flow_order(nodes, edges):
    # Stable topological order only for acyclic flow input. Cycles keep their
    # supplied node order and all directed edges; no temporal facts are inferred.
    pending = list(nodes)
    output, emitted = [], set()
    while pending:
        ready = [node for node in pending if all(e['from'] in emitted for e in edges if e['to'] == node['id'])]
        if not ready:
            return list(nodes)
        for node in ready:
            output.append(node)
            emitted.add(node['id'])
            pending.remove(node)
    return output


def _graph(doc, diagram):
    nodes, edges = diagram['nodes'], diagram['edges']
    ordered = _flow_order(nodes, edges) if diagram['kind'] == 'flow' else nodes
    width = doc.limits.page_width - 2 * _MARGIN - (len(edges) + 1) * 26 - 32
    slots = {node['id']: [] for node in nodes}
    for edge in edges:
        slots[edge['from']].append((edge['id'], 'from'))
        slots[edge['to']].append((edge['id'], 'to'))
    boxes, y = {}, 0
    for node in ordered:
        lines = _lines(node['grounded_label'], width - 48, 28)
        height = max(72 + len(lines) * 40, 32 + (len(slots[node['id']]) + 1) * 14)
        boxes[node['id']] = (_MARGIN, y, width, height, lines)
        y += height + 22
    doc.ensure(y)
    origin = doc.y
    right = _MARGIN + width

    def port(node_id, edge_id, direction):
        _, top, _, height, _ = boxes[node_id]
        values = slots[node_id]
        index = values.index((edge_id, direction))
        return int(origin + top + 16 + (index + 1) * (height - 32) / (len(values) + 1))

    for index, edge in enumerate(edges):
        lane = right + 32 + (index + 1) * 26
        sy, ty = port(edge['from'], edge['id'], 'from'), port(edge['to'], edge['id'], 'to')
        points = ((right, sy), (lane, sy), (lane, ty), (right, ty))
        arrow = ((right, ty), (right + 14, ty - 6), (right + 14, ty + 6))
        color = _EDGE_COLORS[index % len(_EDGE_COLORS)]
        doc.draw.line(points, fill=color, width=3)
        doc.draw.polygon(arrow, fill=color)
        cy = (sy + ty) // 2
        doc.draw.ellipse((lane - 12, cy - 12, lane + 12, cy + 12), fill='white', outline=color, width=2)
        text = str(index + 1)
        tw = int(_width(text, _font(18)))
        ref = f"edge:{edge['id']}"
        doc.line(text, lane - tw // 2, cy - 9, 18, ref=ref, color=color)
        doc.routes.append(EdgeRoute(edge['id'], edge['from'], edge['to'], points, arrow))
    source_number = {node['id']: index + 1 for index, node in enumerate(nodes)}
    for node in ordered:
        x, top, width, height, lines = boxes[node['id']]
        top += origin
        ref = f"node:{node['id']}"
        doc.draw.rounded_rectangle((x, top, x + width, top + height), radius=12,
                                   fill=_ACCENT, outline=_BORDER, width=2)
        doc.line(f'{source_number[node["id"]]:02d}', x + 24, top + 18, 24, ref=ref, color=_MUTED)
        for i, line in enumerate(lines):
            doc.line(line, x + 24, top + 58 + i * 40, 28, ref=ref)
    doc.y += y
    by_id = {node['id']: node for node in nodes}
    for index, edge in enumerate(edges):
        # The full endpoints and label survive wrapping/page breaks. Numbered
        # arrows and this legend are a pair; never replace edges with text only.
        text = (f'{index + 1}. {by_id[edge["from"]]["grounded_label"]} → '
                f'{by_id[edge["to"]]["grounded_label"]}：{edge["grounded_label"]}')
        height = len(_lines(text, doc.limits.page_width - 2 * _MARGIN, 30)) * 44 + 18
        if index == 0:
            doc.ensure(min(height + 70, doc.bottom - 94))
            doc.text('关系说明', size=32)
        elif height <= doc.bottom - 94 - 70 and doc.y + height > doc.bottom:
            doc.new_page()
            doc.text('关系说明（续）', size=32)
        doc.text(text, ref=f"edge:{edge['id']}", keep_together=True)


def render_summary_visual_png(visual: SummaryVisual, frame_bytes: Mapping[str, bytes], *,
                              title: str, limits: RenderLimits = DEFAULT_LIMITS) -> PngRenderResult:
    """Render complete graphics or raise; never return partial/truncated output.

    frame_bytes keys are visual.frames[*].id, NOT paths or screenshot indices.
    Authoritative body/receipt validation belongs to the caller. Semantic order
    preserves scene array order, or node array followed by edge array order.
    """
    _check_limits(limits)
    identity = renderer_identity()
    try:
        checked = _validate(visual, title)
        frames = _frames(checked, frame_bytes, limits)
    except (TypeError, KeyError, AttributeError, OverflowError, UnicodeError) as exc:
        raise SummaryVisualPngError('invalid_visual') from exc
    semantics = []
    if checked['presentation'] == 'comic':
        by_id = {frame['id']: frame for frame in checked['frames']}
        for scene in checked['scenes']:
            semantics.append(SemanticItem('scene', scene['id'], scene['grounded_label'], tuple(scene['block_ids']),
                frame_id=scene['frame_id'], timestamp_seconds=by_id[scene['frame_id']]['timestamp_seconds']))
    else:
        diagram = checked['diagram']
        for node in diagram['nodes']:
            semantics.append(SemanticItem('node', node['id'], node['grounded_label'], tuple(node['block_ids'])))
        for edge in diagram['edges']:
            semantics.append(SemanticItem('edge', edge['id'], edge['grounded_label'], tuple(edge['block_ids']),
                from_id=edge['from'], to_id=edge['to']))
    label = '画面分镜 · 原始画面' if checked['presentation'] == 'comic' else '信息图 · 已保存正文'
    doc = _Document(limits, label, semantics)
    try:
        if title:
            doc.text(title, size=40, gap=30)
        if checked['presentation'] == 'comic':
            _comic(doc, checked, frames)
        elif checked['diagram']['kind'] in ('cards', 'comparison'):
            _cards(doc, checked['diagram'])
        else:
            _graph(doc, checked['diagram'])
        doc.seal()
        pages = tuple(doc.pages)
    finally:
        doc.close()
    bound = dict(protocol=PROTOCOL, renderer=identity, visual=checked, title=title, limits=asdict(limits),
                 frames={key: sha256(value).hexdigest() for key, value in frames.items()},
                 pages=[dict(sha256=page.sha256, width=page.width, height=page.height,
                             semantic_refs=page.semantic_refs) for page in pages],
                 semantic_order=[asdict(item) for item in semantics])
    return PngRenderResult(pages, tuple(semantics), tuple(identity.items()), sha256(_json(bound)).hexdigest())


# Names, not original function objects: monkeypatched/reloaded implementations
# cannot accidentally inherit the digest of the old callable. Source and frozen
# execution both construct these registries in memory; no source path is read.
_IDENTITY_FUNCTION_NAMES = tuple(sorted(name for name, value in globals().copy().items()
    if (isinstance(value, FunctionType) or hasattr(value, '__wrapped__'))
    and getattr(value, '__module__', None) == __name__))
_IDENTITY_CLASS_NAMES = tuple(sorted(name for name, value in globals().copy().items()
    if isinstance(value, type) and value.__module__ == __name__))
