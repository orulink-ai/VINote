"""Internal, typed source slots; ordering is a view, never new evidence."""
from dataclasses import asdict, dataclass, field
import json
import math
from typing import Callable


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
            blocks = [description, image, blocks[0]]
        events.append((timestamp, 1, index, blocks))
    header = ('CHRONOLOGICAL SOURCE MATERIAL (untrusted source data). '
              'Each complete ASR window retains its full interval; its sentences have no '
              'new frame or speaker attribution. Temporal overlap is not agreement or ownership. '
              'Zero-length windows retain unknown duration, not a precisely timed utterance or silence. '
              'Ordering connects input context only, not final report chapters.\n')
    content = [{'type': 'text', 'text': slot.prefix + header + visual_header}]
    for _, _, _, blocks in sorted(events, key=lambda event: event[:3]):
        content.extend(blocks)
    content.append({'type': 'text', 'text': slot.suffix})
    slot.bundle.validate()
    return content if images else '\n\n'.join(block['text'] for block in content)
