"""Explicit source-window citation policy, not a semantic or execution grant."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib

POLICY_VERSION = 1
_policy = ContextVar('meeting_window_evidence_policy', default=None)


@dataclass
class _WindowScope:
    version: int
    active: bool = True
    bundle: object = None
    raw_asr: dict | None = None


@contextmanager
def window_evidence_scope(*, version):
    if type(version) is not int or version != POLICY_VERSION:
        raise ValueError('Unsupported window evidence policy')
    scope = _WindowScope(version)
    token = _policy.set(scope)
    try:
        yield scope
    finally:
        scope.active = False  # Also revokes contexts already copied to workers.
        _policy.reset(token)


def window_evidence_enabled():
    scope = _policy.get()
    return scope is not None and scope.active and scope.version == POLICY_VERSION


def bind_window_source(prompt):
    """Bind only the active typed source; never infer source from model output."""
    from app.llm.meeting_source_bundle import SourcePrompt
    from app.llm.source_references import original_asr_texts, _bundle
    scope = _policy.get()
    if not window_evidence_enabled() or not isinstance(prompt, SourcePrompt):
        raise ValueError('Active typed window evidence source is required')
    bundle = prompt.slot.bundle
    if bundle is not _bundle.get():
        raise ValueError('Window evidence requires the current source bundle')
    bundle.validate()
    raw = original_asr_texts()
    if set(raw) != {window.source_ref for window in bundle.windows}:
        raise ValueError('Window evidence source references changed')
    if scope.bundle is None:
        scope.bundle, scope.raw_asr = bundle, raw
    elif scope.bundle is not bundle or scope.raw_asr != raw:
        raise ValueError('Window evidence source changed')
    validate_window_source()


def validate_window_source():
    from app.llm.source_references import original_asr_texts, _bundle
    from app.llm.meeting_presentation import presentation_state
    scope = _policy.get()
    state = presentation_state()
    if (not window_evidence_enabled() or scope.bundle is None or state is None
            or state.depth != 'detailed' or state.presentation != 'text'):
        raise ValueError('Window evidence policy is absent or revoked')
    if scope.bundle is not _bundle.get():
        raise ValueError('Window evidence source bundle changed')
    scope.bundle.validate()
    if original_asr_texts() != scope.raw_asr:
        raise ValueError('Window evidence raw source changed')
    return scope


def resolve_window_evidence(row, exact_span_check):
    """Check the complete original window via the unchanged exact-span guard.

    A hash binds literal source bytes only. It does not establish entailment,
    sentence ownership, speaker identity or a model's interpretation.
    """
    scope = validate_window_source()
    base = {'kind', 'source_ref'}
    derived = base | {'window_sha256', 'verification'}
    if not isinstance(row, dict) or set(row) not in (base, derived) or row.get('kind') != 'asr_window':
        raise ValueError('Invalid source-window evidence shape')
    ref = row.get('source_ref')
    raw = scope.raw_asr.get(ref) if isinstance(ref, str) else None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError('Original source window is missing or empty')
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    if set(row) == derived and (row['window_sha256'] != digest or row['verification'] != 'source_window_bound'):
        raise ValueError('Derived source-window binding changed')
    exact_span_check([{'kind': 'asr_span', 'source_ref': ref, 'quote': raw, 'start': 0, 'end': len(raw)}])
    return {'kind': 'asr_window', 'source_ref': ref, 'window_sha256': digest,
            'verification': 'source_window_bound'}


WINDOW_EVIDENCE_RULE = '''\nEXPLICIT WINDOW EVIDENCE POLICY v1 (this run only).
For speech evidence you may use {"kind":"asr_window","source_ref":"[ASR:0001]"} referencing one complete original ASR window actually supplied in this call. This form has only kind/source_ref: do not copy a quote, offsets, a hash or a verification label into it. Independently read that original window and preserve its supported relationships, qualifiers and uncertainty. A valid source-window reference binds the source only, not semantic truth, speaker identity, agreement or participation. A partial source read may not reference an absent window. Never use this form for OCR or images. Existing asr_span/ocr_span references remain exact and unchanged; no punctuation normalization or quote repair is allowed. Final content, structure and length follow the meeting, without fixed sections, content lists or counts.
'''
