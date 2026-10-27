"""Frozen OCR display lines, never source authority or evidence repair."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

from app.services.video_evidence_service import VideoEvidenceError, _frame_digest

POLICY = 1
ALGORITHM = 'insert-lf-after-ocr-line-v1'
FILE = 'meeting_ocr_layout.json'
_MAX_SIDECAR = 12 * 1024 * 1024
_MAX_VIEW_CHARS = 160000


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _fail():
    raise VideoEvidenceError('本次画面文字布局无法核验，未调用模型')


def _text_sha(value):
    if value is None:
        return None
    if not isinstance(value, str):
        _fail()
    return _sha(value.encode('utf-8'))


def _read(path, *, optional=False):
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
        _fail()
    if optional and not path.exists():
        return None
    try:
        with path.open('rb') as stream:
            raw = stream.read(_MAX_SIDECAR + 1)
        if len(raw) > _MAX_SIDECAR:
            _fail()
        return raw
    except OSError:
        _fail()


def _json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError('duplicate field')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))


def _lines(raw, item):
    """Unsupported/incomplete layouts stay explicitly flat, without partial rows."""
    if not isinstance(raw, str) or not raw or '\n' in raw or '\r' in raw:
        return (), 'flat'
    if not isinstance(item, dict) or item.get('status') != 'recognized' or item.get('text') != raw:
        return (), 'flat'
    lines = item.get('lines')
    if not isinstance(lines, list) or not 1 <= len(lines) <= 2048:
        return (), 'flat'
    cursor, spans = 0, []
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get('text'), str) or not line['text']:
            return (), 'flat'
        start = raw.find(line['text'], cursor)
        if start < 0 or raw[cursor:start].strip():
            return (), 'flat'
        end = start + len(line['text'])
        spans.append((start, end)); cursor = end
    if raw[cursor:].strip():
        return (), 'flat'
    return tuple(spans), 'insert_lf_v1'


def _view(raw, spans):
    if not spans:
        return raw
    parts, cursor = [], 0
    for index, (start, end) in enumerate(spans):
        parts.append(raw[cursor:end])
        if index + 1 < len(spans):
            parts.append('\n')
        cursor = end
    parts.append(raw[cursor:])
    value = ''.join(parts)
    if value.replace('\n', '') != raw:
        _fail()
    return value


def _frame_snapshot(evidence):
    rows = []
    for index, frame in enumerate(evidence.frames):
        digest = _frame_digest(frame.image_path)
        if evidence._summary_frame_hashes.get(frame.image_path) != digest:
            _fail()
        rows.append({'source_ref': f'[FRAME:{index + 1:04d}]', 'frame_sha256': digest,
                     'timestamp': frame.timestamp, 'sample_offsets': list(frame.sample_offsets),
                     'ocr_status': frame.ocr_status, 'raw_text_sha256': _text_sha(frame.ocr_text)})
    return rows


@dataclass(frozen=True)
class FrozenOCRLayout:
    folder: Path
    owner: str
    task_id: str
    sidecar_sha256: str
    revision: str
    _source_sha256: str | None
    _frames_json: bytes
    _rows_json: bytes

    def validate(self, evidence):
        for name, expected in [('recording_owner', self.owner), ('.task_id', self.task_id)]:
            if _read(self.folder / name).decode('utf-8') != expected:
                _fail()
        if _sha(_read(self.folder / FILE)) != self.sidecar_sha256:
            _fail()
        ocr_raw = _read(self.folder / 'meeting_video_ocr.json', optional=True)
        if (_sha(ocr_raw) if ocr_raw is not None else None) != self._source_sha256:
            _fail()
        if _bytes(_frame_snapshot(evidence)) != self._frames_json:
            _fail()

    def records(self, evidence, records):
        self.validate(evidence)
        rows = _json(self._rows_json)
        result = []
        for record, row in zip(records, rows):
            value = dict(record)
            value['visible_text'] = _view(value['visible_text'], row['line_spans'])
            value['ocr_view_mode'] = row['mode']
            if _text_sha(value['visible_text']) != row['view_sha256']:
                _fail()
            result.append(value)
        if len(result) != len(records) or len(result) != len(rows):
            _fail()
        return result


def freeze_layout(evidence, *, task_dir, owner, task_id, context_binding, policy):
    """Called only by a newly accepted, claimed summary task after preflight/OCR.

    The returned digest still needs binding to its accepted DB receipt before
    attach_layout can expose this view. Disk JSON alone authorizes nothing.
    """
    if type(policy) is not int or policy != POLICY:
        _fail()
    folder = Path(task_dir)
    if folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)():
        _fail()
    for name, expected in [('recording_owner', owner), ('.task_id', task_id)]:
        if _read(folder / name).decode('utf-8') != expected:
            _fail()
    if not isinstance(context_binding, dict) or set(context_binding) != {'context_revision', 'source_version', 'snapshot_sha256'}:
        _fail()
    before = _frame_snapshot(evidence)
    ocr_raw = _read(folder / 'meeting_video_ocr.json', optional=True)
    ocr_sha = _sha(ocr_raw) if ocr_raw is not None else None
    payload = None
    if ocr_raw is not None:
        try:
            payload = _json(ocr_raw)
        except (ValueError, UnicodeError, RecursionError):
            payload = None
    if isinstance(payload, dict):
        # An explicitly foreign material is not an unsupported layout.
        if payload.get('owner', owner) != owner or payload.get('task_id', task_id) != task_id:
            _fail()
    usable = (isinstance(payload, dict) and type(payload.get('protocol')) is int
              and payload['protocol'] == 1 and payload.get('kind') == 'desktop_derived_ocr'
              and payload.get('owner') == owner and payload.get('task_id') == task_id
              and payload.get('accepted_context_binding') == context_binding
              and payload.get('status') == 'completed' and payload.get('inputs_verified_after') is True
              and isinstance(payload.get('items'), list) and len(payload['items']) == len(before)
              and isinstance(payload.get('source_frames'), list) and len(payload['source_frames']) == len(before))
    rows, total = [], 0
    for i, (frame, source) in enumerate(zip(evidence.frames, before)):
        item = payload['items'][i] if usable else None
        origin = payload['source_frames'][i] if usable else None
        matched = (isinstance(item, dict) and isinstance(origin, dict)
                   and item.get('expected_sha256') == origin.get('sha256') == source['frame_sha256']
                   and origin.get('timestamp') == frame.timestamp
                   and origin.get('sample_offsets') == frame.sample_offsets)
        spans, mode = _lines(frame.ocr_text, item if matched and frame.ocr_status == 'recognized' else None)
        view = _view(frame.ocr_text, spans)
        total += len(view or '')
        rows.append({**source, 'line_spans': spans, 'mode': mode,
                     'view_sha256': _text_sha(view)})
    if total > _MAX_VIEW_CHARS:
        _fail()
    saved = {'protocol': POLICY, 'algorithm': ALGORITHM, 'owner': owner, 'task_id': task_id,
             'accepted_context_binding': context_binding, 'ocr_sidecar_sha256': ocr_sha,
             'offset_unit': 'python_unicode_codepoint', 'end': 'exclusive', 'frames': rows}
    encoded = _bytes(saved)
    if len(encoded) > _MAX_SIDECAR or _bytes(_frame_snapshot(evidence)) != _bytes(before):
        _fail()
    after_ocr = _read(folder / 'meeting_video_ocr.json', optional=True)
    if (_sha(after_ocr) if after_ocr is not None else None) != ocr_sha:
        _fail()
    destination = folder / FILE
    if destination.is_symlink():
        _fail()
    try:
        with destination.open('xb') as stream:
            stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
    except OSError:
        _fail()
    sidecar_sha = _sha(encoded)
    revision = _sha(_bytes({'policy': POLICY, 'algorithm': ALGORITHM, 'layout_sha256': sidecar_sha}))
    return FrozenOCRLayout(folder, owner, task_id, sidecar_sha, revision, ocr_sha, _bytes(before), _bytes(rows))


def attach_layout(evidence, frozen, *, accepted_revision):
    if not isinstance(frozen, FrozenOCRLayout) or accepted_revision != frozen.revision:
        _fail()
    frozen.validate(evidence)
    evidence._ocr_layout = frozen
