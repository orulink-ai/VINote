"""Graphic-only P7, full-body per-part visibility; no production changes."""
import copy

import pytest

from app.llm.meeting_final_claim_ledger import FinalLedgerError
from app.llm.meeting_final_review import validate_review_envelope
from app.llm.meeting_single_copy_projection7 import core_review7, project_review7, validate_review7, _visible_part_ranges7
from app.llm.source_references import bind_source_references
from app.models.transcript import TranscriptSegment
from test_meeting_final_claim_ledger import RAW, draft, review


def example():
    value = review(); value['protocol'] = 7
    value['title_ref'] = {'block_id': 'B1', 'part_index': 0}
    value['blocks'] = [{'id': 'B1', 'parts': [RAW]}]
    for claim in value['claims']:
        claim.pop('text'); claim.pop('block_ids')
        claim['part_ref'] = {'block_id': 'B1', 'part_index': 0}
    value['visual'] = {'protocol': 3, 'scenes': [], 'diagram': {'kind': 'cards', 'edges': [],
        'nodes': [{'id': 'VN1', 'label_ref': {'block_id': 'B1', 'part_index': 0, 'claim_ids': ['C1']}}]}}
    return value


def full_check(value, *, raw=RAW):
    with bind_source_references([TranscriptSegment(0, 10, raw)]):
        return validate_review7(value, draft(), depth='detailed', presentation='infographic')


def second_block(value, parts):
    value['blocks'].append({'id': 'B2', 'parts': parts})
    for index in range(len(parts)):
        claim = copy.deepcopy(value['claims'][0]); claim['id'] = f'NEW{index}'
        claim['part_ref'] = {'block_id': 'B2', 'part_index': index}
        value['claims'].append(claim)


def test_exact_character_ranges_for_unselected_parts_including_unicode():
    value = example(); second_block(value, ['😀甲。', ' 乙，丙。'])
    before = copy.deepcopy(value)
    core = core_review7(value, presentation='infographic')
    spans = _visible_part_ranges7(value, core)
    joined = '\n\n'.join(row['markdown'] for row in core['blocks'])
    assert spans[('B2', 0)] == (len(RAW) + 2, len(RAW) + 2 + 3)
    for block in value['blocks']:
        for index, part in enumerate(block['parts']):
            start, end = spans[(block['id'], index)]
            assert joined[start:end] == part
    assert full_check(value).markdown == RAW + '\n\n😀甲。 乙，丙。'
    assert value == before


@pytest.mark.parametrize('parts', [
    ['Visible words. ', '[shown](', 'hidden-destination', ')'],
    ['Visible words. ', '`', 'code interpreted as content', '`'],
    ['Visible words. ', '**', 'bold body', '**'],
    ['Visible words. ', '&amp;'],
    ['Visible words. ', '\\*'],
    ['Visible words.\n', '[hidden]: https://example.invalid'],
    ['[hidden]: https://example.invalid'],
    ['<span>hidden</span>'],
    ['# Discussion points'],
    ['> Quote'],
    ['    Indented code'],
    ['- List item'],
    ['---'],
    ['Visible\nsecond line'],
    [' spaced paragraph '],
])
def test_unselected_included_parts_cannot_hide_inside_an_otherwise_visible_block(parts):
    value = example(); second_block(value, parts)
    before = copy.deepcopy(value)
    with pytest.raises(FinalLedgerError) as error: full_check(value)
    assert error.value.code == 'invalid_body_part_visibility'
    assert value == before


@pytest.mark.parametrize('opener,closer', [('```', '```'), ('~~~', '~~~'), ('<!--', '-->'), ('<script>', '</script>')])
def test_identical_visible_occurrence_does_not_authorize_hidden_later_position(opener, closer):
    value = example(); second_block(value, [opener])
    value['blocks'].append({'id': 'B3', 'parts': [RAW]})
    value['blocks'].append({'id': 'B4', 'parts': [closer]})
    for block in ['B3', 'B4']:
        c = copy.deepcopy(value['claims'][0]); c['id'] = 'C_' + block
        c['part_ref'] = {'block_id': block, 'part_index': 0}; value['claims'].append(c)
    with pytest.raises(FinalLedgerError) as error: full_check(value)
    assert error.value.code == 'invalid_body_part_visibility'


@pytest.mark.parametrize('presentation', ['text', 'html', 'illustrated'])
def test_new_profile_never_constrains_existing_non_graphic_hosts(presentation):
    with pytest.raises(FinalLedgerError) as error: core_review7(example(), presentation=presentation)
    assert error.value.code == 'invalid_presentation'
    if presentation != 'illustrated':
        value = review(); value['blocks'][0]['markdown'] = '# Content-chosen heading\n\n' + RAW
        with bind_source_references([TranscriptSegment(0, 10, RAW)]):
            assert validate_review_envelope(value, draft(), depth='detailed', presentation=presentation)[0].markdown.startswith('# ')


def test_supported_content_can_start_a_paragraph_without_a_synthetic_heading_claim():
    value = example(); result = full_check(value)
    assert result.markdown == RAW
    assert {c['id'] for c in result.claims} == {'C1', 'C2'}
    assert all(c['text'] == RAW for c in result.claims)
    assert 'Discussion points' not in result.markdown


@pytest.mark.parametrize('where', ['part', 'block'])
def test_no_free_heading_escape_hatch(where):
    value = example()
    if where == 'part': value['blocks'][0]['parts'].insert(0, 'Discussion points. ')
    else: value['blocks'].append({'id': 'B2', 'parts': ['Discussion points.']})
    with pytest.raises(FinalLedgerError): full_check(value)


def test_graphic_same_part_not_same_block_or_same_text():
    value = example(); value['blocks'][0]['parts'] = [RAW, ' A second statement.']
    value['claims'][1]['part_ref']['part_index'] = 1
    value['visual']['diagram']['nodes'][0]['label_ref']['claim_ids'] = ['C2']
    with pytest.raises(FinalLedgerError) as error: project_review7(value, presentation='infographic')
    assert error.value.code == 'invalid_visual_claim_part'


@pytest.mark.parametrize('bad', ['punctuation', 'offset', 'repeat', 'material', 'id'])
def test_source_and_original_accounting_guards_remain_strict(bad):
    value = example(); raw = RAW
    if bad == 'punctuation': value['claims'][0]['evidence'][0]['quote'] = RAW.replace('closed.', 'closed?')
    if bad == 'offset': value['claims'][0]['evidence'][0].update(start=True, end=len(RAW))
    if bad == 'repeat': raw = RAW + ' ' + RAW
    if bad == 'material': value['claims'][0]['material'] = False
    if bad == 'id': value['claims'][0]['id'] = 'renamed'
    with pytest.raises(FinalLedgerError): full_check(value, raw=raw)


@pytest.mark.parametrize('index', [True, -1, 0.0, '0', None, []])
def test_strict_part_reference(index):
    value = example(); value['claims'][0]['part_ref']['part_index'] = index
    with pytest.raises(FinalLedgerError): full_check(value)


def test_parts_are_not_independent_source_truth_proofs():
    value = example(); value['blocks'][0]['parts'] = ['Hold 18.625 mA even when the blue latch is open.']
    assert full_check(value).markdown == value['blocks'][0]['parts'][0]


@pytest.mark.parametrize('parts', [
    ['[visible](', 'https://example.invalid/hidden-only', ')'],
    ['[visible](https://example.invalid "', RAW, '")'],
    ['Visible paragraph.\n\n', '[label]: https://example.invalid/definition-only'],
    ['```', '\n' + RAW + '\n', '```'],
])
def test_copernicus_exact_hidden_part_counterexamples_are_rejected(parts):
    value = example(); second_block(value, parts)
    before = copy.deepcopy(value)
    with pytest.raises(FinalLedgerError) as error: full_check(value)
    assert error.value.code == 'invalid_body_part_visibility'
    assert value == before
