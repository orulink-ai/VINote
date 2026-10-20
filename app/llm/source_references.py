"""Request-local references to unchanged source material, never new evidence."""
from contextlib import contextmanager
from contextvars import ContextVar
import re

_indices = ContextVar('meeting_source_indices', default=None)
_texts = ContextVar('meeting_original_asr_texts', default=None)
_draft_observer = ContextVar('meeting_working_draft_observer', default=None)
_bundle = ContextVar('meeting_chronological_source', default=None)


@contextmanager
def bind_chronological_source(segments, render, *, enabled=True):
    if not enabled:
        token = _bundle.set(None)
        try:
            yield None
        finally:
            _bundle.reset(token)
        return
    from app.llm.meeting_source_bundle import freeze_source
    active = True
    bundle = freeze_source(segments, render, segment_reference,
                           lambda: active and _bundle.get() is bundle)
    token = _bundle.set(bundle)
    try:
        yield bundle
    finally:
        active = False
        _bundle.reset(token)


def source_prompt(prefix: str, source: str, suffix: str):
    """Standalone/legacy builders stay strings; admitted meetings get a typed slot."""
    bundle = _bundle.get()
    if bundle is None:
        return prefix + source + suffix
    from app.llm.meeting_source_bundle import SourcePrompt, SourceSlot
    bundle.validate()
    if source != bundle.original_text:
        raise ValueError('Meeting source changed before prompt construction')
    return SourcePrompt(SourceSlot(prefix, bundle, suffix))


@contextmanager
def capture_working_draft(observer):
    token = _draft_observer.set(observer)
    try:
        yield
    finally:
        _draft_observer.reset(token)


def record_working_draft(text: str):
    observer = _draft_observer.get()
    if observer is not None:
        observer(text)


@contextmanager
def bind_source_references(segments):
    indices = {}
    for index, segment in enumerate(segments):
        indices.setdefault(id(segment), index)
    token = _indices.set(indices)
    texts = _texts.set({asr_reference(index): segment.text for index, segment in enumerate(segments)
                       if indices[id(segment)] == index})
    try:
        yield
    finally:
        _texts.reset(texts)
        _indices.reset(token)


def original_asr_texts():
    """Snapshot of raw ASR only, excluding rendered timing/speaker diagnostics."""
    return dict(_texts.get() or {})


def asr_reference(index: int) -> str:
    return f'[ASR:{index + 1:04d}]'


def segment_reference(segment, fallback_index: int) -> str:
    indices = _indices.get()
    if indices is not None and id(segment) not in indices:
        raise ValueError('Summary source reference changed within the request')
    return asr_reference(indices[id(segment)] if indices is not None else fallback_index)


def frame_reference(index: int) -> str:
    return f'[FRAME:{index + 1:04d}]'


def without_internal_references(markdown: str) -> str:
    """Only our reserved reference syntax is hidden; business text stays intact."""
    return re.sub(r'\[(?:ASR|FRAME):[0-9]{4,}\]', '', markdown).strip()
