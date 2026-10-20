"""summary-visual/1: validated model data, immutable sidecar, authenticated reads.

No inference, source fetching, text synthesis or screenshot selection occurs here.
The caller supplies reviewed blocks and already prepared task-owned JPEGs. Save
may run before result.json is committed; reads require the successful saved body.
Missing/invalid sidecars never establish completed graphical output.
"""
import copy
import hashlib
import io
import json
import math
import os
import re
import stat
import uuid

from PIL import Image
from fastapi import HTTPException

from app.db import session_scope
from app.db_models import SourceRequestDB

SIDECAR = 'summary_visual.json'
MAX_WIRE_BYTES = 128 * 1024
_TITLE_NOT_REQUIRED = object()
_ID = re.compile(r'[A-Za-z0-9_\[\]:.\-]{1,64}\Z')
_TASK = re.compile(r'[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}\Z')


class SummaryVisualError(ValueError):
    """Unverifiable data; never an instruction to retry generation."""


def _need(condition):
    if not condition:
        raise SummaryVisualError('图形数据无法核验，正文仍保留')


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _object(value, keys):
    _need(type(value) is dict and set(value) == set(keys))


def _rows(value, maximum, minimum=0):
    _need(type(value) is list and minimum <= len(value) <= maximum)


def _id(value):
    _need(isinstance(value, str) and _ID.fullmatch(value) is not None)


def _label(value):
    _need(isinstance(value, str) and bool(value.strip()) and len(value) <= 120
          and not re.search(r'[\x00-\x1f\x7f]', value))


def validate_summary_visual(value, *, task_id, presentation, markdown):
    """Validate exact wire fields and references; return a detached wire value.

    Grounding checks literal block membership, not semantic truth. The existing
    whole-source model review remains responsible for factual relationships.
    """
    _need(isinstance(markdown, str) and isinstance(task_id, str) and _TASK.fullmatch(task_id)
          and presentation in {'comic', 'infographic'})
    _need(len(_json(value)) <= MAX_WIRE_BYTES)
    _object(value, ['visual_protocol', 'task_id', 'presentation', 'body_sha256',
                    'blocks', 'frames', 'scenes', 'diagram'])
    _need(type(value['visual_protocol']) is int and value['visual_protocol'] == 1
          and value['task_id'] == task_id and value['presentation'] == presentation
          and value['body_sha256'] == _sha(markdown.encode('utf-8')))
    _rows(value['blocks'], 64, 1)
    blocks = {}
    for block in value['blocks']:
        _object(block, ['id', 'text', 'claim_ids'])
        _id(block['id'])
        text = block['text']
        _need(isinstance(text, str) and bool(text.strip()) and len(text) <= 6000 and text in markdown)
        _rows(block['claim_ids'], 64)
        for claim in block['claim_ids']:
            _id(claim)
        _need(len(set(block['claim_ids'])) == len(block['claim_ids']) and block['id'] not in blocks)
        blocks[block['id']] = block

    def references(ids):
        _rows(ids, 8, 1)
        for key in ids:
            _id(key)
        _need(len(set(ids)) == len(ids) and all(key in blocks for key in ids)
              and any(blocks[key]['claim_ids'] for key in ids))
        return ids

    def grounded(label, ids):
        _label(label)
        _need(any(label in blocks[key]['text'] for key in ids))

    _rows(value['frames'], 8)
    _rows(value['scenes'], 8)
    frames, indices, frame_blocks, scene_ids = {}, set(), {}, set()
    for frame in value['frames']:
        _object(frame, ['id', 'screenshot_index', 'timestamp_seconds', 'grounded_label'])
        _id(frame['id'])
        _label(frame['grounded_label'])
        index, stamp = frame['screenshot_index'], frame['timestamp_seconds']
        try:
            finite = type(stamp) in (int, float) and math.isfinite(stamp)
        except OverflowError:
            finite = False
        _need(type(index) is int and 0 <= index <= 7 and index not in indices
              and finite and stamp >= 0
              and frame['id'] not in frames)
        frames[frame['id']] = frame
        indices.add(index)
    for scene in value['scenes']:
        _object(scene, ['id', 'block_ids', 'frame_id', 'grounded_label'])
        _id(scene['id'])
        _id(scene['frame_id'])
        refs = references(scene['block_ids'])
        grounded(scene['grounded_label'], refs)
        _need(scene['id'] not in scene_ids and scene['frame_id'] in frames)
        frame_blocks.setdefault(scene['frame_id'], []).extend(refs)
        scene_ids.add(scene['id'])
    if presentation == 'comic':
        _need(bool(frames) and bool(scene_ids) and value['diagram'] is None
              and set(frames) == set(frame_blocks))
        for key, frame in frames.items():
            grounded(frame['grounded_label'], frame_blocks[key])
    else:
        _need(not value['scenes'])
        diagram = value['diagram']
        _object(diagram, ['kind', 'nodes', 'edges'])
        _need(isinstance(diagram['kind'], str) and diagram['kind'] in {'cards', 'comparison', 'flow', 'relationship'})
        _rows(diagram['nodes'], 12, 1)
        _rows(diagram['edges'], 20)
        nodes, edges = set(), set()
        for node in diagram['nodes']:
            _object(node, ['id', 'block_ids', 'grounded_label'])
            _id(node['id'])
            grounded(node['grounded_label'], references(node['block_ids']))
            _need(node['id'] not in nodes)
            nodes.add(node['id'])
        for edge in diagram['edges']:
            _object(edge, ['id', 'from', 'to', 'block_ids', 'grounded_label'])
            for key in ['id', 'from', 'to']:
                _id(edge[key])
            _need(edge['id'] not in edges and edge['from'] in nodes and edge['to'] in nodes)
            grounded(edge['grounded_label'], references(edge['block_ids']))
            edges.add(edge['id'])
        _need(diagram['kind'] not in {'cards', 'comparison'} or not edges)
    return copy.deepcopy(value)


def build_summary_visual(*, task_id, presentation, markdown, blocks, frames, scenes, diagram):
    """Add server identity/hash to caller's reviewed wire data; never repair it."""
    return validate_summary_visual({
        'visual_protocol': 1, 'task_id': task_id, 'presentation': presentation,
        'body_sha256': _sha(markdown.encode('utf-8')), 'blocks': blocks,
        'frames': frames, 'scenes': scenes, 'diagram': diagram,
    }, task_id=task_id, presentation=presentation, markdown=markdown)


def reviewed_visual_blocks(review, *, presentation=None):
    """Project validated legacy audit or v4/v5 ledger; never rewrite raw.

    Call only after existing fact-protocol finalization succeeds. This function
    performs no evidence review and cannot turn a failed/raw draft into a final.
    """
    if type(review) is dict and type(review.get('protocol')) is int and review['protocol'] == 7:
        from app.llm.meeting_single_copy_projection7 import project_review7
        review, _ = project_review7(review, presentation=presentation)
    if type(review) is dict and type(review.get('protocol')) is int and review['protocol'] == 6:
        from app.llm.meeting_visual_projection6 import core_review6
        review = core_review6(review)
    if type(review) is dict and type(review.get('protocol')) is int and review['protocol'] == 5:
        from app.llm.meeting_visual_projection import core_review5
        review = core_review5(review)
    _need(type(review) is dict and type(review.get('protocol')) is int and review['protocol'] in (2, 3, 4))
    _rows(review.get('blocks'), 64, 1)
    final = review['protocol'] == 4
    audit = review.get('claims' if final else 'audit')
    claim_key = 'id' if final else 'claim_id'
    _need(type(audit) is list)
    rows, claims = {}, set()
    for block in review['blocks']:
        _need(type(block) is dict)
        _id(block.get('id'))
        _need(block['id'] not in rows and isinstance(block.get('markdown'), str))
        rows[block['id']] = {'id': block['id'], 'text': block['markdown'], 'claim_ids': []}
    for item in audit:
        _need(type(item) is dict)
        _id(item.get(claim_key))
        _need(item[claim_key] not in claims)
        claims.add(item[claim_key])
        refs = item.get('block_ids')
        _need(type(refs) is list and all(isinstance(ref, str) and ref in rows for ref in refs)
              and len(set(refs)) == len(refs))
        _need(item.get('disposition') in ('included', 'rejected', 'omitted_for_depth'))
        if item['disposition'] == 'included':
            _need(bool(refs))
            for key in refs:
                rows[key]['claim_ids'].append(item[claim_key])
        else:
            _need(not refs)
    projected = list(rows.values())
    # finalize() joins blocks with two LF and strips the joined body's outer
    # whitespace. Mirror only those two boundaries in this detached projection;
    # raw review bytes, internal block whitespace and saved-body hash stay intact.
    projected[0]['text'] = projected[0]['text'].lstrip()
    projected[-1]['text'] = projected[-1]['text'].rstrip()
    return projected


def reviewed_claim_sources(review, *, presentation=None):
    """Read explicit final evidence, without OCR, donor reads or inference.

    This is a projection after successful finalization, not fresh authorization
    or semantic validation. Saved reads additionally bind the original raw file
    hash and the accepted operation/Origin/model fingerprint.
    """
    if type(review) is dict and type(review.get('protocol')) is int and review['protocol'] == 7:
        from app.llm.meeting_single_copy_projection7 import project_review7
        review, _ = project_review7(review, presentation=presentation)
    if type(review) is dict and type(review.get('protocol')) is int and review['protocol'] == 6:
        from app.llm.meeting_visual_projection6 import core_review6
        review = core_review6(review)
    if type(review) is dict and type(review.get('protocol')) is int and review['protocol'] == 5:
        from app.llm.meeting_visual_projection import core_review5
        review = core_review5(review)
    _need(type(review) is dict and type(review.get('protocol')) is int and review['protocol'] == 4)
    reviewed_visual_blocks(review, presentation=presentation)
    result = {}
    for claim in review['claims']:
        if claim['disposition'] != 'included':
            continue
        evidence = claim.get('evidence')
        _need(type(evidence) is list and bool(evidence))
        refs = set()
        for row in evidence:
            _need(type(row) is dict and isinstance(row.get('source_ref'), str))
            kind, ref = row.get('kind'), row['source_ref']
            _need(isinstance(kind, str) and kind in {'asr_span', 'ocr_span', 'frame_observation'}
                  and re.fullmatch(r'\[ASR:[0-9]{4,}\]' if kind == 'asr_span' else r'\[FRAME:[0-9]{4,}\]', ref))
            refs.add(ref)
        result[claim['id']] = sorted(refs)
    return result


def _plain(path):
    for part in (path, *path.parents):
        info = part.lstat()
        _need(not stat.S_ISLNK(info.st_mode) and not getattr(part, 'is_junction', lambda: False)())


def _read(path, maximum):
    _plain(path)
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= maximum)
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    # CPython/Windows reports different ctime semantics for lstat and fstat.
    # Compare ctime within each API and identity/mtime across both APIs.
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_nlink)
    last = path.lstat()
    _need(len(data) <= maximum and identity(before) == identity(opened) == identity(after)
          == identity(last) and before.st_ctime_ns == last.st_ctime_ns
          and opened.st_ctime_ns == after.st_ctime_ns)
    return data


def _decode(data):
    def pairs(rows):
        value = {}
        for key, item in rows:
            _need(key not in value)
            value[key] = item
        return value
    return json.loads(data.decode('utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda _: _need(False))


def _load(path, maximum=16384):
    return _decode(_read(path, maximum))


def _folder(artifacts, owner, task):
    _need(isinstance(owner, str) and bool(owner.strip()) and isinstance(task, str) and _TASK.fullmatch(task))
    folder = artifacts.find_task_dir(task)
    _need(folder is not None)
    _plain(folder)
    _need(folder.resolve().parent == artifacts.output_dir.resolve()
          and not (folder / 'recording_deleted').exists()
          and _read(folder / 'recording_owner', 512).decode('utf-8') == owner
          and _read(folder / '.task_id', 100).decode('utf-8') == task)
    return folder


def _authorization(folder, owner, task, presentation, sessions):
    """Rebuild the persisted submission fingerprint; disk metadata is not auth."""
    from app.services.source_request_service import _fingerprint
    from app.services.meeting_summary_regeneration import SummaryConfirmation, _submission, _digest
    from app.services.task_model_source import SNAPSHOT_FILE
    metadata = _load(folder / 'summary_presentation.json')
    link = _load(folder / 'new_generation.json')
    snapshot = _load(folder / SNAPSHOT_FILE)
    # The accepted receipt commits the historical snapshot. Reading an artifact
    # must not re-authorize the current connection, retrieve credentials or call
    # its provider; revoked connections do not erase already saved results.
    _need(type(snapshot) is dict and type(snapshot.get('version')) is int
          and snapshot['version'] == 1 and snapshot.get('owner') == owner
          and snapshot.get('mode') == 'cloud')
    _need(type(metadata.get('protocol')) is int and metadata['protocol'] == 1
          and metadata.get('task_id') == task and metadata.get('presentation') == presentation
          and metadata.get('operation_id') == link.get('operation_id')
          and link.get('presentation') == presentation and link.get('confirmed') is True
          and metadata.get('parent_task_id') == link.get('parent_task_id')
          and metadata.get('source_version') == link.get('source_version')
          and metadata.get('content_depth') == (link.get('content_depth') or 'detailed')
          and metadata.get('model_name') == link.get('model_name') == snapshot.get('llm_model'))
    if link.get('contract') == 'meeting-summary-only-v1':
        body = SummaryConfirmation(**{key: link[key] for key in SummaryConfirmation.model_fields if key in link})
        submission = _submission(link['parent_task_id'], body)
        marker = 'summary_generation_started'
    elif link.get('contract') == 'meeting-fresh-asr-v1':
        from app.services.task_fresh_asr import _submission as fresh_submission
        submission = fresh_submission(link)
        _need(link['snapshot_sha256'] == _digest(snapshot))
        marker = 'new_generation_started'
    else:
        raise SummaryVisualError('图形缺少可核验的版本回执')
    _need(_read(folder / marker, 100) == b'claimed')
    with sessions() as db:
        with db.no_autoflush:
            row = db.get(SourceRequestDB, (owner, link['operation_id']))
            _need(row is not None and row.state == 'accepted' and row.task_id == task
                  and row.fingerprint == _fingerprint(submission))
            if marker == 'summary_generation_started':
                _need(json.loads(row.receipt_json or '{}').get('summary_snapshot_sha256') == _digest(snapshot))
            return {'operation_id': row.operation_id, 'fingerprint': row.fingerprint,
                    'snapshot_sha256': _digest(snapshot)}


def _screenshots(folder, visual):
    result = {}
    for frame in visual['frames']:
        name = f"summary-source-{frame['screenshot_index']}.jpg"
        data = _read(folder / 'screenshots' / name, 2 * 1024 * 1024)
        with Image.open(io.BytesIO(data)) as image:
            _need(image.format == 'JPEG' and 0 < image.width <= 4096 and 0 < image.height <= 4096)
            # JPEG verify() alone does not decode its entropy stream: a valid
            # header with a truncated body must not establish a ready screenshot.
            image.load()
        result[name] = _sha(data)
    return result


def _review_binding(folder, wire, *, presentation, result_title=_TITLE_NOT_REQUIRED):
    _need(presentation == wire['presentation'])
    raw = _read(folder / 'meeting_fact_review.json', 4 * 1024 * 1024)
    artifact = _decode(raw)
    _need(type(artifact.get('protocol')) is int and artifact['protocol'] == 1
          and isinstance(artifact.get('raw_response'), str))
    # Match the existing fact-protocol parser's optional JSON fence envelope.
    text = artifact['raw_response'].strip()
    fenced = text.startswith('```json') and text.endswith('```')
    if fenced:
        text = text[7:-3].strip()
    review = _decode(text.encode('utf-8'))
    if type(review.get('protocol')) is int and review['protocol'] == 7:
        from app.llm.meeting_single_copy_projection7 import project_review7
        _need(not fenced)
        core, plan = project_review7(review, presentation=presentation)
        _need(wire['blocks'] == reviewed_visual_blocks(review, presentation=presentation))
        body = '\n\n'.join(row['markdown'] for row in core['blocks']).strip()
        _need(wire['body_sha256'] == _sha(body.encode('utf-8')))
        _need(plan['scenes'] == wire['scenes'] and plan['diagram'] == wire['diagram'])
        selected = {}
        for scene in plan['scenes']:
            selected.setdefault(scene['frame_id'], scene['grounded_label'])
        _need(len(wire['frames']) == len(selected))
        for index, ((key, label), frame) in enumerate(zip(selected.items(), wire['frames'])):
            _need(frame['id'] == key and frame['screenshot_index'] == index
                  and frame['grounded_label'] == label)
        reviewed_claim_sources(review, presentation=presentation)
        from app.llm.meeting_single_copy_projection7 import metadata_title7
        source_title = _load(folder / 'audio_meta.json', 4 * 1024 * 1024).get('title')
        expected_title = metadata_title7(review, presentation=presentation, source_title=source_title)
        if result_title is not _TITLE_NOT_REQUIRED:
            _need(isinstance(result_title, str) and result_title == expected_title)
        return _sha(raw)
    _need(wire['blocks'] == reviewed_visual_blocks(review, presentation=presentation))
    if review['protocol'] == 6:
        from app.llm.meeting_visual_projection6 import project_review6
        _need(not fenced)
        core, plan = project_review6(review, presentation=presentation)
        body = '\n\n'.join(row['markdown'] for row in core['blocks']).strip()
        _need(wire['body_sha256'] == _sha(body.encode('utf-8')))
        _need(plan['scenes'] == wire['scenes'] and plan['diagram'] == wire['diagram'])
        selected = {}
        for scene in plan['scenes']:
            selected.setdefault(scene['frame_id'], scene['grounded_label'])
        _need(len(wire['frames']) == len(selected))
        for index, ((key, label), frame) in enumerate(zip(selected.items(), wire['frames'])):
            _need(frame['id'] == key and frame['screenshot_index'] == index
                  and frame['grounded_label'] == label)
        reviewed_claim_sources(review, presentation=presentation)
    if review['protocol'] == 5:
        from app.llm.meeting_visual_projection import project_review5
        _need(not fenced)
        core, plan = project_review5(review, presentation=presentation)
        body = '\n\n'.join(row['markdown'] for row in core['blocks']).strip()
        _need(wire['body_sha256'] == _sha(body.encode('utf-8')))
        _need(plan['scenes'] == wire['scenes'] and plan['diagram'] == wire['diagram'])
        # Screenshot bytes/timestamps remain host metadata; all model-derived
        # frame identity/order/captions must reconstruct from raw5 exactly.
        selected = {}
        for scene in plan['scenes']:
            selected.setdefault(scene['frame_id'], scene['grounded_label'])
        _need(len(wire['frames']) == len(selected))
        for index, ((key, label), frame) in enumerate(zip(selected.items(), wire['frames'])):
            _need(frame['id'] == key and frame['screenshot_index'] == index
                  and frame['grounded_label'] == label)
        reviewed_claim_sources(review, presentation=presentation)
    if review['protocol'] == 4:
        _need(not fenced and set(review) == {'protocol', 'blocks', 'claims', 'visual'})
        plan = review['visual']
        _object(plan, ['scenes', 'diagram'])
        _need(plan['scenes'] == wire['scenes'] and plan['diagram'] == wire['diagram'])
        sources = reviewed_claim_sources(review, presentation=presentation)
        by_block = {row['id']: row['claim_ids'] for row in wire['blocks']}
        if wire['presentation'] == 'comic':
            for scene in wire['scenes']:
                _need(any(scene['frame_id'] in sources[key]
                          for block in scene['block_ids'] for key in by_block[block]))
        else:
            _need(wire['presentation'] == 'infographic' and not wire['frames'])
    return _sha(raw)


def _frozen_visual_context(folder, owner, task, requested, sessions):
    # A disk choice alone is not authority: the existing DB-bound
    # submission/snapshot gate must validate it before projection.
    presentation = _load(folder / 'new_generation.json').get('presentation')
    _need(isinstance(presentation, str) and presentation in {'comic', 'infographic'})
    bound = _authorization(folder, owner, task, presentation, sessions)
    _need(requested == presentation)
    return presentation, bound


def save_summary_visual(artifacts, owner, task_id, markdown, visual, *, sessions=None):
    """Persist only caller-supplied, validated data. Existing sidecars are immutable.

    Call after preparing exact screenshot files, before marking the task success.
    No note/body/status/receipt is changed here. A failed save must not be reported
    as a graphical success. Re-saving identical data is read-only and idempotent.
    """
    wire = validate_summary_visual(visual, task_id=task_id,
                                  presentation=visual.get('presentation'), markdown=markdown)
    folder = _folder(artifacts, owner, task_id)
    presentation, bound = _frozen_visual_context(
        folder, owner, task_id, wire['presentation'], sessions or session_scope)
    payload = {'artifact_protocol': 1, 'owner': owner, 'receipt': bound,
               'review_sha256': _review_binding(folder, wire, presentation=presentation),
               'screenshots': _screenshots(folder, wire), 'visual': wire}
    data = _json(payload)
    path = folder / SIDECAR
    if path.exists() or path.is_symlink():
        _need(_load(path, MAX_WIRE_BYTES + 8192) == payload)
        return wire
    temporary = folder / f'.summary_visual.{uuid.uuid4().hex}.tmp'
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # link publishes atomically without replacing another writer's result.
        try:
            os.link(temporary, path)
        except FileExistsError:
            _need(_load(path, MAX_WIRE_BYTES + 8192) == payload)
        temporary.unlink()
        if os.name != 'nt':
            descriptor = os.open(folder, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    return wire


def read_summary_visual(artifacts, owner, task_id, *, sessions=None):
    """Read only; invalid/missing/unfinished data returns None, never dispatches."""
    try:
        folder = _folder(artifacts, owner, task_id)
        payload = _load(folder / SIDECAR, MAX_WIRE_BYTES + 8192)
        _object(payload, ['artifact_protocol', 'owner', 'receipt', 'review_sha256', 'screenshots', 'visual'])
        _need(type(payload['artifact_protocol']) is int and payload['artifact_protocol'] == 1
              and payload['owner'] == owner and _load(folder / 'status.json')['status'] == 'success')
        # JSON preserves the exact string returned to the client. note.md uses
        # OS newline translation on Windows and is not the savedBody authority.
        result = _load(folder / 'result.json', 4 * 1024 * 1024)
        markdown = result['markdown']
        wire = validate_summary_visual(payload['visual'], task_id=task_id,
                                      presentation=payload['visual'].get('presentation'), markdown=markdown)
        presentation, bound = _frozen_visual_context(
            folder, owner, task_id, wire['presentation'], sessions or session_scope)
        _need(payload['review_sha256'] == _review_binding(
            folder, wire, presentation=presentation, result_title=result.get('title'))
              and payload['receipt'] == bound
              and payload['screenshots'] == _screenshots(folder, wire))
        _need(_folder(artifacts, owner, task_id) == folder)
        return wire
    except (OSError, ValueError, TypeError, KeyError, AttributeError, HTTPException):
        return None
