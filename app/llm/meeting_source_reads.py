"""Opt-in source-read data planning/projection; no inference or execution authority."""
import copy
from dataclasses import dataclass, field
import hashlib
import json
import math
import re

from app.llm.meeting_source_bundle import (
    PreparedSourceContent, SourceUnit, source_content_sha256,
)


def _require(condition, message='Invalid source-read data'):
    if not condition:
        raise ValueError(message)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'Duplicate JSON key')
        result[key] = value
    return result


def _decode(raw):
    _require(isinstance(raw, str))
    try:
        return json.loads(raw, object_pairs_hook=_object,
                          parse_constant=lambda _: _require(False, 'Non-finite JSON'))
    except (TypeError, json.JSONDecodeError):
        raise ValueError('Invalid complete source-read JSON') from None


@dataclass(frozen=True)
class SourceRead:
    index: int  # One-based, also the ID namespace.
    start_seconds: float
    end_seconds: float
    content: list
    allowed_refs: frozenset[str]
    input_sha256: str
    root_input_sha256: str
    _prepared: PreparedSourceContent = field(repr=False, compare=False)

    def validate(self):
        self._prepared.validate()
        _require(self.root_input_sha256 == self._prepared.root_sha256)
        _require(source_content_sha256(self.content) == self.input_sha256,
                 'Partial source-read payload changed')


def _units(prepared):
    _require(type(prepared.header_index) is int and prepared.header_index == 0
             and prepared.footer_index == len(prepared) - 1 and len(prepared) >= 2)
    _require(all(isinstance(prepared[i], dict) and prepared[i].get('type') == 'text'
                 and isinstance(prepared[i].get('text'), str)
                 for i in (prepared.header_index, prepared.footer_index)))
    cursor, refs = 1, set()
    duration = prepared.duration_seconds
    _require(_number(duration) and duration > 0, 'Verified whole-source duration is required')
    for unit in prepared.units:
        _require(type(unit) is SourceUnit and unit.kind in {'asr', 'frame'}, 'Unknown source unit')
        prefix = 'ASR' if unit.kind == 'asr' else 'FRAME'
        _require(isinstance(unit.source_ref, str)
                 and re.fullmatch(r'\[' + prefix + r':\d{4,}\]', unit.source_ref) is not None
                 and unit.source_ref not in refs)
        refs.add(unit.source_ref)
        _require(type(unit.block_start) is int and type(unit.block_stop) is int
                 and unit.block_start == cursor < unit.block_stop <= prepared.footer_index,
                 'Source units do not exactly cover the payload')
        cursor = unit.block_stop
        _require(_number(unit.start_seconds) and _number(unit.end_seconds)
                 and 0 <= unit.start_seconds <= unit.end_seconds <= duration)
        blocks = prepared[unit.block_start:unit.block_stop]
        _require(isinstance(blocks[0], dict) and blocks[0].get('type') == 'text'
                 and isinstance(blocks[0].get('text'), str))
        record = _decode(blocks[0]['text'].split('\n', 1)[0])
        _require(isinstance(record, dict) and record.get('source_ref') == unit.source_ref)
        if unit.kind == 'asr':
            _require(len(blocks) == 1 and unit.sample_offsets == ()
                     and record.get('start_seconds') == unit.start_seconds
                     and record.get('end_seconds') == unit.end_seconds)
        else:
            _require(len(blocks) == 2 and isinstance(blocks[1], dict)
                     and blocks[1].get('type') == 'image_url'
                     and unit.start_seconds == unit.end_seconds
                     and record.get('offset_seconds') == unit.start_seconds
                     and type(unit.sample_offsets) is tuple and bool(unit.sample_offsets)
                     and isinstance(record.get('sample_offsets'), list)
                     and tuple(record['sample_offsets']) == unit.sample_offsets
                     and all(_number(t) and 0 <= t <= duration for t in unit.sample_offsets))
    _require(cursor == prepared.footer_index and bool(refs), 'Unaccounted or empty source units')
    return refs


def split_source_reads(prepared, groups=3):
    """Three duration bins; complete overlapping units, globally unchanged refs.

    No default host opts into this. Call each read.validate() before dispatch.
    Hashes cover UTF-8 json.dumps(list, ensure_ascii=False, allow_nan=False).
    """
    _require(isinstance(prepared, PreparedSourceContent), 'Typed prepared source is required')
    _require(type(groups) is int and groups == 3, 'Only three source reads are supported')
    prepared.validate()
    all_refs = _units(prepared)
    duration, reads = prepared.duration_seconds, []

    def point_bin(t):
        return min(int(t / duration * groups), groups - 1)

    for i in range(groups):
        start, end = duration * i / groups, duration * (i + 1) / groups
        selected = []
        for unit in prepared.units:
            if unit.kind == 'frame':
                include = any(point_bin(t) == i for t in unit.sample_offsets)
            elif unit.start_seconds == unit.end_seconds:
                include = point_bin(unit.start_seconds) == i
            else:
                include = unit.start_seconds < end and unit.end_seconds > start
            if include:
                selected.append(unit)
        header, footer = copy.deepcopy(prepared[0]), copy.deepcopy(prepared[-1])
        notice = (f'\nPARTIAL SOURCE READ {i + 1}/{groups}: interval {start!r}–{end!r} seconds. '
                  'This is an incomplete source selection, not final minutes or a whole-source review. '
                  'Read intervals are not final report sections; report structure follows the meeting. '
                  'References remain global; whole overlapping windows/frames may repeat in other reads. '
                  'Use only the sources actually supplied in this read; absence is not evidence of absence.\n')
        header['text'] += notice
        footer['text'] += notice
        content = [header]
        for unit in selected:
            content.extend(copy.deepcopy(prepared[unit.block_start:unit.block_stop]))
        content.append(footer)
        reads.append(SourceRead(i + 1, start, end, content,
                     frozenset(u.source_ref for u in selected), source_content_sha256(content),
                     prepared.root_sha256, prepared))
    _require(set().union(*(r.allowed_refs for r in reads)) == all_refs, 'Source coverage lost')
    for read in reads:
        read.validate()
    return tuple(reads)


@dataclass(frozen=True)
class ReadIdMap:
    topics: tuple[tuple[str, str], ...]
    claims: tuple[tuple[str, str], ...]


class PartitionedDraft(str):
    """Lossless ID projection of separate raw reads, never a single model response."""
    __slots__ = ('_raw_reads', '_id_maps', '_allowed_refs', '_raw_sha256')

    def __new__(cls, value, *, raw_reads, id_maps, allowed_refs):
        result = super().__new__(cls, value)
        object.__setattr__(result, '_raw_reads', tuple(raw_reads))
        object.__setattr__(result, '_id_maps', tuple(id_maps))
        object.__setattr__(result, '_allowed_refs', tuple(allowed_refs))
        object.__setattr__(result, '_raw_sha256', tuple(
            hashlib.sha256(raw.encode('utf-8')).hexdigest() for raw in raw_reads))
        return result

    def __setattr__(self, name, value):
        raise AttributeError('Partitioned draft provenance is read-only')

    raw_reads = property(lambda self: self._raw_reads)
    id_maps = property(lambda self: self._id_maps)
    allowed_refs = property(lambda self: self._allowed_refs)
    raw_sha256 = property(lambda self: self._raw_sha256)
    provenance_kind = property(lambda self: 'partitioned_source_reads_p3')

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


def _ids(rows):
    _require(isinstance(rows, list) and all(isinstance(r, dict) for r in rows))
    ids = [r.get('id') for r in rows]
    _require(all(_text(key) for key in ids) and len(ids) == len(set(ids)), 'Duplicate/invalid IDs')
    return ids


def combine_source_reads(rawstrings, allowed_refs):
    """Strict raw P3 shape/ref checks, no quote repair, dedup or semantic verdict.

    Exact span/visual evidence is still checked by the existing full-source
    review. Merely allowing a ref here does not verify its quote or its meaning.
    """
    _require(isinstance(rawstrings, (tuple, list)) and len(rawstrings) == 3
             and isinstance(allowed_refs, (tuple, list)) and len(allowed_refs) == 3)
    topics, claims, maps, refs_by_read = [], [], [], []
    for i, (raw, refs) in enumerate(zip(rawstrings, allowed_refs), 1):
        _require(isinstance(refs, (set, frozenset))
                 and all(isinstance(ref, str) and re.fullmatch(r'\[(?:ASR|FRAME):\d{4,}\]', ref)
                         for ref in refs))
        refs_by_read.append(frozenset(refs))
        value = _decode(raw)
        _require(isinstance(value, dict) and set(value) == {'protocol', 'topics', 'claims'}
                 and type(value['protocol']) is int and value['protocol'] == 3)
        topic_ids, claim_ids = _ids(value['topics']), _ids(value['claims'])
        tm = {key: f'R{i}_{key}' for key in topic_ids}
        cm = {key: f'R{i}_{key}' for key in claim_ids}
        for topic in value['topics']:
            _require(set(topic) == {'id', 'title'} and _text(topic['title']))
            topics.append({**topic, 'id': tm[topic['id']]})
        for claim in value['claims']:
            _require(set(claim) == {'id', 'topic_id', 'field', 'text', 'material', 'evidence'}
                     and isinstance(claim['topic_id'], str) and claim['topic_id'] in tm
                     and _text(claim['field']) and _text(claim['text'])
                     and type(claim['material']) is bool
                     and isinstance(claim['evidence'], list) and bool(claim['evidence']))
            for evidence in claim['evidence']:
                _require(isinstance(evidence, dict))
                kind, ref = evidence.get('kind'), evidence.get('source_ref')
                _require(kind in ('asr_span', 'ocr_span', 'frame_observation')
                         and isinstance(ref, str) and ref in refs, 'Evidence outside this source read')
                key = 'observation' if kind == 'frame_observation' else 'quote'
                permitted = {'kind', 'source_ref', key} | ({'start', 'end'} if key == 'quote' else set())
                _require(set(evidence) <= permitted and _text(evidence.get(key))
                         and ref.startswith('[ASR:' if kind == 'asr_span' else '[FRAME:'))
                if 'start' in evidence or 'end' in evidence:
                    _require(type(evidence.get('start')) is int and type(evidence.get('end')) is int
                             and 0 <= evidence['start'] < evidence['end']
                             and evidence['end'] - evidence['start'] == len(evidence[key]))
            claims.append({**copy.deepcopy(claim), 'id': cm[claim['id']],
                           'topic_id': tm[claim['topic_id']]})
        maps.append(ReadIdMap(tuple(tm.items()), tuple(cm.items())))
    return PartitionedDraft(json.dumps({'protocol': 3, 'topics': topics, 'claims': claims},
                            ensure_ascii=False, allow_nan=False), raw_reads=rawstrings,
                            id_maps=maps, allowed_refs=refs_by_read)
