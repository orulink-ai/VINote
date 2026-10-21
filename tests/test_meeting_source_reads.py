"""Offline source-read conservation and strict lossless draft projection."""
import copy
from dataclasses import FrozenInstanceError, replace
import hashlib
import json

import pytest

from app.llm.meeting_source_bundle import (
    PreparedSourceContent, SourceBundle, SourcePrompt, SourceSlot, SourceUnit,
    SourceWindow, chronological_content, source_content_sha256,
)
from app.llm.meeting_source_reads import (
    PartitionedDraft, combine_source_reads, split_source_reads,
)


def material(visual_header='HEADER\n{"duration_seconds": 30, "scan_complete": true}'):
    windows = (SourceWindow('[ASR:0001]', 5, 25, 'FULL crossing\n  Ω\tunchanged'),
               SourceWindow('[ASR:0002]', 0, 10, 'EARLY raw'),
               SourceWindow('[ASR:0003]', 10, 10, 'UNKNOWN duration'))
    records = [
        {'source_ref': '[FRAME:0001]', 'offset_seconds': 15, 'sample_offsets': [9, 21],
         'visible_text': 'wrong OCR\n Ω  ', 'layout': {'line_spans': [[0, 5]], 'revision': 'opaque'}},
        {'source_ref': '[FRAME:0002]', 'offset_seconds': 10, 'sample_offsets': [10],
         'visible_text': '原文\t不改', 'metadata': ['timeline']},
        {'source_ref': '[FRAME:0003]', 'offset_seconds': 30, 'sample_offsets': [30],
         'visible_text': '', 'ocr_status': 'unavailable'},
    ]
    packets = [({'type': 'text', 'text': r['source_ref'] + ' description'},
                {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,AA{i}=',
                                                   'detail': 'high'}})
               for i, r in enumerate(records)]
    prompt = SourcePrompt(SourceSlot('PREFIX', SourceBundle(windows, 'ORIGINAL', lambda: None), 'FOOTER'))
    return prompt, records, packets, visual_header


def prepared():
    prompt, records, packets, header = material()
    return chronological_content(prompt, visual_header=header, records=records, packets=packets)


def test_whole_wire_and_text_only_match_prechange_golden_bytes():
    prompt, records, packets, header = material()
    content = chronological_content(prompt, visual_header=header, records=records, packets=packets)
    assert isinstance(content, list) and isinstance(content, PreparedSourceContent)
    assert source_content_sha256(content) == 'c4d2a0a80d86b3a77f8cf708f892733834c80d14d6d9e54f8fa4592617a937fe'
    text = chronological_content(prompt, visual_header=header, records=records)
    assert type(text) is str
    assert hashlib.sha256(text.encode()).hexdigest() == '44cc2ba2bb621c6bfffeacf083e04720db0ff0b28d02b8f539215c5a0d9ddf74'
    assert json.dumps(copy.deepcopy(content), ensure_ascii=False) == json.dumps(list(content), ensure_ascii=False)


def test_three_duration_bins_keep_indivisible_units_global_refs_and_actual_samples():
    full = prepared()
    before = json.dumps(full, ensure_ascii=False)
    reads = split_source_reads(full)
    assert len(reads) == 3
    assert [(r.start_seconds, r.end_seconds) for r in reads] == [(0, 10), (10, 20), (20, 30)]
    assert [r.allowed_refs for r in reads] == [
        frozenset({'[ASR:0001]', '[ASR:0002]', '[FRAME:0001]'}),
        frozenset({'[ASR:0001]', '[ASR:0003]', '[FRAME:0002]'}),
        frozenset({'[ASR:0001]', '[FRAME:0001]', '[FRAME:0003]'})]
    # Frame1's representative offset 15 does not move its actual samples 9/21 into bin2.
    for read in reads:
        expected = []
        for unit in full.units:
            if unit.source_ref in read.allowed_refs:
                expected.extend(full[unit.block_start:unit.block_stop])
        assert read.content[1:-1] == expected
        assert 'PARTIAL SOURCE READ' in read.content[0]['text']
        assert 'not final report sections' in read.content[-1]['text']
        assert read.content[0]['text'].startswith(full[0]['text'])
        assert read.content[-1]['text'].startswith(full[-1]['text'])
        assert read.root_input_sha256 == full.root_sha256
        read.validate()
    assert json.dumps(full, ensure_ascii=False) == before


def test_metadata_is_read_only_and_block_ranges_are_complete():
    full = prepared()
    assert full.header_index == 0 and full.footer_index == len(full) - 1
    assert len(full.units) == 6
    assert full.units[0].offset_seconds is None
    assert [u.offset_seconds for u in full.units if u.kind == 'frame'] == [10, 15, 30]
    with pytest.raises(AttributeError): full.units = ()
    with pytest.raises(FrozenInstanceError): full.units[0].source_ref = '[ASR:9999]'
    assert [u.kind for u in full.units] == ['asr', 'asr', 'asr', 'frame', 'frame', 'frame']


@pytest.mark.parametrize('groups', [True, 0, 2, 4, 3.0])
def test_invalid_group_count_rejected(groups):
    with pytest.raises(ValueError): split_source_reads(prepared(), groups=groups)


@pytest.mark.parametrize('change', ['payload', 'unknown_kind', 'missing_unit', 'bad_range',
                                    'wrong_ref', 'wrong_samples', 'short_duration', 'no_duration'])
def test_root_mutation_or_unaccounted_units_rejected(change):
    full = prepared()
    if change == 'payload':
        full[1]['text'] += 'mutated'
    else:
        units, duration = list(full.units), full.duration_seconds
        if change == 'unknown_kind': units[0] = replace(units[0], kind='inferred')
        elif change == 'missing_unit': units.pop()
        elif change == 'bad_range': units[0] = replace(units[0], block_stop=3)
        elif change == 'wrong_ref': units[0] = replace(units[0], source_ref='[ASR:9999]')
        elif change == 'wrong_samples': units[-1] = replace(units[-1], sample_offsets=(29,))
        elif change == 'short_duration': duration = 20
        else: duration = None
        full = PreparedSourceContent(copy.deepcopy(list(full)), units=units,
                                     duration_seconds=duration, validate_source=lambda: None)
    with pytest.raises(ValueError): split_source_reads(full)


def test_partial_and_original_mutation_are_checked_before_dispatch():
    full = prepared()
    read = split_source_reads(full)[0]
    read.content[1]['text'] += 'changed'
    with pytest.raises(ValueError): read.validate()
    read = split_source_reads(full)[0]
    full[-1]['text'] += 'changed'
    with pytest.raises(ValueError): read.validate()
    with pytest.raises(ValueError): split_source_reads(list(prepared()))


def draft(ref='[ASR:0001]'):
    return {'protocol': 3, 'topics': [{'id': 'T1', 'title': 'Variable topic Ω'}],
            'claims': [{'id': 'C1', 'topic_id': 'T1', 'field': 'condition',
                        'text': 'Original proposition\n  Ω', 'material': True,
                        'evidence': [{'kind': 'asr_span', 'source_ref': ref,
                                      'quote': ' 原 quote\t ', 'start': 4, 'end': 15}]}]}


def raw(value):
    return json.dumps(value, ensure_ascii=False)


def test_combination_only_namespaces_ids_preserves_duplicate_claims_and_raw_provenance():
    value = draft()
    # Explicit offsets retain their original character count; no searching/repair.
    value['claims'][0]['evidence'][0]['end'] = 4 + len(value['claims'][0]['evidence'][0]['quote'])
    raws = [raw(value)] * 3
    combined = combine_source_reads(raws, [frozenset({'[ASR:0001]'})] * 3)
    assert isinstance(combined, PartitionedDraft) and isinstance(combined, str)
    assert combined.raw_reads == tuple(raws)
    assert combined.provenance_kind == 'partitioned_source_reads_p3'
    projection = json.loads(combined)
    assert len(projection['claims']) == len(projection['topics']) == 3
    for i in range(3):
        claim = projection['claims'][i]
        assert claim['id'] == f'R{i+1}_C1' and claim['topic_id'] == f'R{i+1}_T1'
        assert {k: v for k, v in claim.items() if k not in ('id', 'topic_id')} == {
            k: v for k, v in value['claims'][0].items() if k not in ('id', 'topic_id')}
        assert combined.id_maps[i].claims == (('C1', f'R{i+1}_C1'),)
    with pytest.raises(AttributeError): combined.raw_reads = ()
    assert copy.deepcopy(combined) is combined


@pytest.mark.parametrize('change', ['foreign_ref', 'duplicate_claim', 'duplicate_topic', 'dangling_topic',
    'wrong_protocol', 'bool_protocol', 'material_int', 'missing_quote', 'bad_offsets', 'unknown_key',
    'duplicate_json_key', 'nan', 'fenced', 'truncated', 'wrong_kind_ref'])
def test_invalid_read_fails_without_partial_projection(change):
    value = draft()
    value['claims'][0]['evidence'][0].pop('start')
    value['claims'][0]['evidence'][0].pop('end')
    if change == 'foreign_ref': value['claims'][0]['evidence'][0]['source_ref'] = '[ASR:0002]'
    elif change == 'duplicate_claim': value['claims'].append(copy.deepcopy(value['claims'][0]))
    elif change == 'duplicate_topic': value['topics'].append(copy.deepcopy(value['topics'][0]))
    elif change == 'dangling_topic': value['claims'][0]['topic_id'] = 'T2'
    elif change == 'wrong_protocol': value['protocol'] = 4
    elif change == 'bool_protocol': value['protocol'] = True
    elif change == 'material_int': value['claims'][0]['material'] = 1
    elif change == 'missing_quote': value['claims'][0]['evidence'][0].pop('quote')
    elif change == 'bad_offsets': value['claims'][0]['evidence'][0].update(start=True, end=7)
    elif change == 'unknown_key': value['blocks'] = []
    elif change == 'wrong_kind_ref': value['claims'][0]['evidence'][0]['kind'] = 'ocr_span'
    bad = raw(value)
    if change == 'duplicate_json_key': bad = bad.replace('"protocol": 3', '"protocol":3,"protocol":3')
    elif change == 'nan': bad = bad.replace('"material": true', '"material": NaN')
    elif change == 'fenced': bad = '```json\n' + bad + '\n```'
    elif change == 'truncated': bad = bad[:-1]
    with pytest.raises(ValueError):
        combine_source_reads([bad, raw({'protocol': 3, 'topics': [], 'claims': []}),
                              raw({'protocol': 3, 'topics': [], 'claims': []})],
                             [frozenset({'[ASR:0001]'})] * 3)


def test_empty_read_drafts_are_legal_without_inventing_topics_or_claims():
    empty = raw({'protocol': 3, 'topics': [], 'claims': []})
    assert json.loads(combine_source_reads([empty] * 3, [frozenset()] * 3)) == json.loads(empty)


@pytest.mark.parametrize('header', ['no duration', '{"duration_seconds": true}',
                                   '{"duration_seconds": 30}{"duration_seconds": 30}'])
def test_ambiguous_or_missing_duration_never_guessed_from_last_frame(header):
    prompt, records, packets, _ = material()
    full = chronological_content(prompt, visual_header=header, records=records, packets=packets)
    assert full.duration_seconds is None
    with pytest.raises(ValueError, match='duration'): split_source_reads(full)


def test_frame_observation_and_ocr_are_preserved_without_verifying_meaning_or_fixing_text():
    value = draft('[FRAME:0001]')
    evidence = [{'kind': 'frame_observation', 'source_ref': '[FRAME:0001]',
                 'observation': 'Fallible original path interpretation Ω'},
                {'kind': 'ocr_span', 'source_ref': '[FRAME:0001]', 'quote': 'bad OCR\t Ω'}]
    value['claims'][0]['evidence'] = evidence
    empty = raw({'protocol': 3, 'topics': [], 'claims': []})
    result = combine_source_reads([raw(value), empty, empty],
                                  [frozenset({'[FRAME:0001]'}), frozenset(), frozenset()])
    assert json.loads(result)['claims'][0]['evidence'] == evidence
    assert 'verification' not in json.loads(result)['claims'][0]['evidence'][0]


def test_reclaimed_source_validation_blocks_prepared_and_partial_data():
    full = prepared()
    live = [True]
    def validate():
        if not live[0]: raise ValueError('source no longer current')
    full = PreparedSourceContent(list(full), units=full.units,
                                 duration_seconds=full.duration_seconds, validate_source=validate)
    read = split_source_reads(full)[0]
    live[0] = False
    with pytest.raises(ValueError, match='current'): read.validate()
    with pytest.raises(ValueError, match='current'): split_source_reads(full)
