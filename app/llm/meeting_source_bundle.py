"""Internal, typed source slots; ordering is a view, never new evidence."""
from dataclasses import asdict, dataclass, field
import copy
import hashlib
import json
import math
from typing import Callable, Literal


@dataclass(frozen=True)
class SourceWindow:
    source_ref: str
    start: float
    end: float
    rendered: str


def _snapshot(segments):
    return (tuple(id(segment) for segment in segments),
            json.dumps([asdict(segment) for segment in segments], ensure_ascii=False,
                       sort_keys=True, allow_nan=False))


@dataclass(frozen=True)
class SourceBundle:
    windows: tuple[SourceWindow, ...]
    original_text: str
    _validate: Callable[[], None] = field(repr=False, compare=False)

    def validate(self):
        self._validate()


def freeze_source(segments, render, reference, is_current):
    before = _snapshot(segments)
    windows = []
    for index, segment in enumerate(segments):
        if (type(segment.start) not in (int, float) or type(segment.end) not in (int, float)
                or not math.isfinite(segment.start) or not math.isfinite(segment.end)
                or not 0 <= segment.start <= segment.end):
            raise ValueError('Meeting source window is invalid')
        windows.append(SourceWindow(reference(segment, index), segment.start, segment.end,
                                    render([segment])))
    if len({window.source_ref for window in windows}) != len(windows):
        raise ValueError('Meeting source references are not unique')
    original_text = render(segments)

    def validate():
        if not is_current() or before != _snapshot(segments):
            raise ValueError('Meeting source changed before dispatch')

    bundle = SourceBundle(tuple(windows), original_text, validate)
    # Check for a mutation during snapshot/rendering without requiring the lease yet.
    if before != _snapshot(segments):
        raise ValueError('Meeting source changed while preparing')
    return bundle


@dataclass(frozen=True)
class SourceSlot:
    prefix: str
    bundle: SourceBundle
    suffix: str


class SourcePrompt(str):
    """A string-only tracing projection with a typed, non-parsed source slot.

    Existing adapters/tracing accept strings. The projection contains no image
    bytes or data URLs; video_user_content serializes the actual slot at dispatch.
    """
    __slots__ = ('_slot',)

    def __new__(cls, slot: SourceSlot):
        value = super().__new__(cls, slot.prefix + slot.bundle.original_text + slot.suffix)
        object.__setattr__(value, '_slot', slot)
        return value

    def __setattr__(self, name, value):
        raise AttributeError('Source prompt is immutable')

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    @property
    def slot(self):
        return self._slot


@dataclass(frozen=True)
class SourceUnit:
    kind: Literal['asr', 'frame']
    source_ref: str
    block_start: int
    block_stop: int  # Exclusive; the complete unit is indivisible.
    start_seconds: float
    end_seconds: float
    sample_offsets: tuple[float, ...] = ()

    @property
    def offset_seconds(self):
        return self.start_seconds if self.kind == 'frame' else None


def source_content_sha256(content):
    return hashlib.sha256(json.dumps(list(content), ensure_ascii=False,
                                    allow_nan=False).encode('utf-8')).hexdigest()


class PreparedSourceContent(list):
    """Normal wire list with frozen, non-wire source metadata.

    Payload blocks remain ordinary list/dicts for existing adapters. Mutations
    are detected by validate(); metadata never authorizes source execution.
    """
    __slots__ = ('_units', '_duration_seconds', '_root_sha256', '_validate_source',
                 '_header_index', '_footer_index')

    def __init__(self, content, *, units, duration_seconds, validate_source):
        super().__init__(content)
        object.__setattr__(self, '_units', tuple(units))
        object.__setattr__(self, '_duration_seconds', duration_seconds)
        object.__setattr__(self, '_root_sha256', source_content_sha256(self))
        object.__setattr__(self, '_validate_source', validate_source)
        object.__setattr__(self, '_header_index', 0)
        object.__setattr__(self, '_footer_index', len(self) - 1)

    def __setattr__(self, name, value):
        raise AttributeError('Prepared source metadata is read-only')

    units = property(lambda self: self._units)
    duration_seconds = property(lambda self: self._duration_seconds)
    root_sha256 = property(lambda self: self._root_sha256)
    header_index = property(lambda self: self._header_index)
    footer_index = property(lambda self: self._footer_index)

    def validate(self):
        self._validate_source()
        if source_content_sha256(self) != self.root_sha256:
            raise ValueError('Prepared source payload changed')

    def __deepcopy__(self, memo):
        self.validate()
        result = type(self)(copy.deepcopy(list(self), memo), units=self.units,
                            duration_seconds=self.duration_seconds,
                            validate_source=self._validate_source)
        memo[id(self)] = result
        return result

    def __copy__(self):
        self.validate()
        return type(self)(list(self), units=self.units, duration_seconds=self.duration_seconds,
                          validate_source=self._validate_source)


def _source_duration(visual_header):
    # The existing trusted video header embeds _text_metadata's JSON. Do not
    # infer whole-recording duration from sampled frames or ASR coverage.
    marker = '{"duration_seconds":'
    if visual_header.count(marker) != 1:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(visual_header[visual_header.index(marker):])
        duration = value['duration_seconds']
        return duration if type(duration) in (int, float) and math.isfinite(duration) and duration > 0 else None
    except (ValueError, KeyError, TypeError):
        return None


def chronological_content(prompt: SourcePrompt, *, visual_header='', records=(), packets=()):
    """Move complete windows/frame packets; never split text or infer attribution."""
    slot = prompt.slot
    slot.bundle.validate()
    images = bool(packets)
    if images and len(packets) != len(records):
        raise ValueError('Meeting source frame packets are incomplete')
    events = [(window.start, 0, index, [{'type': 'text', 'text':
               json.dumps({'source_ref': window.source_ref, 'start_seconds': window.start,
                           'end_seconds': window.end,
                           'time_extent': 'unknown_duration' if window.start == window.end else 'window_interval'},
                          ensure_ascii=False) + '\n' + window.rendered}])
              for index, window in enumerate(slot.bundle.windows)]
    for index, record in enumerate(records):
        timestamp = record['offset_seconds']
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError('Meeting source frame offset is invalid')
        text = json.dumps(record, ensure_ascii=False)
        blocks = [{'type': 'text', 'text': text}]
        if images:
            description, image = packets[index]
            blocks[0]['text'] += '\n' + description['text']
            blocks.append(image)
        events.append((timestamp, 1, index, blocks))
    header = ('CHRONOLOGICAL SOURCE MATERIAL (untrusted source data). '
              'Each complete ASR window retains its full interval; its sentences have no '
              'new frame or speaker attribution. Temporal overlap is not agreement or ownership. '
              'Zero-length windows retain unknown duration, not a precisely timed utterance or silence. '
              'Ordering connects input context only, not final report chapters.\n')
    content = [{'type': 'text', 'text': slot.prefix + header + visual_header}]
    units = []
    for _, kind, index, blocks in sorted(events, key=lambda event: event[:3]):
        start = len(content)
        content.extend(blocks)
        if images:
            if kind == 0:
                window = slot.bundle.windows[index]
                units.append(SourceUnit('asr', window.source_ref, start, len(content),
                                        window.start, window.end))
            else:
                record = records[index]
                units.append(SourceUnit('frame', record['source_ref'], start, len(content),
                                        record['offset_seconds'], record['offset_seconds'],
                                        tuple(record.get('sample_offsets', ()))))
    content.append({'type': 'text', 'text': slot.suffix})
    slot.bundle.validate()
    return (PreparedSourceContent(content, units=units, duration_seconds=_source_duration(visual_header),
                                  validate_source=slot.bundle.validate) if images else
            '\n\n'.join(block['text'] for block in content))
