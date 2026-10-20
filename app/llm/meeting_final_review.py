"""Explicit protocol-4/5/6 presentation envelopes over the strict final ledger.

Projection removes only host-declared fields after exact envelope validation.
It never repairs model JSON, creates claims/audit rows or rewrites raw review.
Legacy fact finalizers and their receipt formats remain independent.
"""
import copy
import json
import re

from app.llm.meeting_final_claim_ledger import (
    CORE_ENVELOPE_RULE, REVIEW_PROTOCOL, FinalLedgerError, decode_final_review,
    validate_final_ledger,
)
from app.llm.meeting_presentation import presentation_state
from app.llm.video_material import visual_source_bindings
from app.llm.meeting_fact_protocol import prepare as prepare_v3
from app.llm.meeting_markdown import figures_are_images


_CORE = {'protocol', 'blocks', 'claims'}
_EXTRAS = {'text': set(), 'html': set(), 'illustrated': {'figures'},
           'comic': {'visual'}, 'infographic': {'visual'}}


def _need(condition, code):
    if not condition:
        raise FinalLedgerError(code)


def prepare_final_draft(text):
    """Decode raw draft before any legacy parser can discard duplicate keys."""
    material = decode_final_review(text)
    _need(isinstance(material, dict) and type(material.get('protocol')) is int
          and material['protocol'] == 3, 'invalid_draft_protocol')
    return prepare_v3(material)


def validate_review_envelope(value, material, *, depth, presentation):
    """Return the checked ledger and detached original versioned envelope."""
    _need(isinstance(presentation, str) and presentation in _EXTRAS, 'invalid_presentation')
    _need(isinstance(value, dict) and set(value) == _CORE | _EXTRAS[presentation], 'invalid_host_envelope')
    if type(value.get('protocol')) is int and value['protocol'] == 6:
        from app.llm.meeting_visual_projection6 import core_review6, project_review6
        _need(presentation in {'comic', 'infographic'}, 'invalid_protocol')
        ledger = validate_final_ledger(core_review6(value), material, depth=depth)
        project_review6(value, presentation=presentation)
        return ledger, copy.deepcopy(value)
    if type(value.get('protocol')) is int and value['protocol'] == 5:
        from app.llm.meeting_visual_projection import core_review5, project_review5
        _need(presentation in {'comic', 'infographic'}, 'invalid_protocol')
        ledger = validate_final_ledger(core_review5(value), material, depth=depth)
        project_review5(value, presentation=presentation)
        return ledger, copy.deepcopy(value)
    ledger = validate_final_ledger({key: value[key] for key in _CORE}, material, depth=depth)
    return ledger, copy.deepcopy(value)


def _illustrated_figures(review, ledger):
    figures = review['figures']
    _need(isinstance(figures, list) and 1 <= len(figures) <= 8, 'invalid_figures')
    blocks = {row['id']: row['markdown'] for row in ledger.blocks}
    included = {row['id']: row for row in ledger.claims if row['disposition'] == 'included'}
    frames, placements, converted = set(), set(), []
    for figure in figures:
        _need(isinstance(figure, dict) and set(figure) == {'frame_ref', 'claim_ids', 'after_block_id', 'caption'},
              'invalid_figure')
        ref, ids, block, caption = (figure[key] for key in ('frame_ref', 'claim_ids', 'after_block_id', 'caption'))
        _need(isinstance(ref, str) and ref in visual_source_bindings() and ref not in frames
              and isinstance(ids, list) and bool(ids)
              and all(isinstance(key, str) and key in included for key in ids)
              and len(ids) == len(set(ids)), 'invalid_figure_sources')
        _need(isinstance(block, str) and block in blocks and block not in placements
              and all(block in included[key]['block_ids']
                      and ref in {row['source_ref'] for row in included[key]['evidence']} for key in ids),
              'invalid_figure_placement')
        passage = blocks[block]
        _need(ledger.markdown.count(passage) == 1 and isinstance(caption, str) and bool(caption.strip())
              and len(caption) <= 160 and not re.search(r'[\[\]<>\r\n]', caption), 'invalid_figure_caption')
        converted.append({'frame_ref': ref, 'fact_ids': sorted(set(ids)),
                          'after_passage': passage, 'caption': caption})
        frames.add(ref)
        placements.add(block)
    markdown = ledger.markdown
    for figure in converted:
        passage = figure['after_passage']
        markdown = markdown.replace(passage, passage + '\n\n' + figure['frame_ref'], 1)
    _need(figures_are_images(markdown, converted), 'invalid_figure_placement')
    return markdown, converted


def finalize_final_review(text, draft):
    """Finalize a structured run; preserve exact raw4/raw5/raw6 on failure too."""
    state = presentation_state()
    _need(state is not None, 'missing_presentation_state')
    state.raw_review = text
    value = decode_final_review(text)
    # The actual new graphic prompt freezes the expected protocol before the
    # response. Standalone legacy finalizers/readback retain their v4 contract.
    if getattr(state, 'expected_review_protocol', None) is not None:
        _need(type(value) is dict and type(value.get('protocol')) is int
              and value['protocol'] == state.expected_review_protocol, 'invalid_protocol')
    ledger, review = validate_review_envelope(value, decode_final_review(draft),
        depth=state.depth, presentation=state.presentation or 'text')
    if state.presentation == 'illustrated':
        markdown, figures = _illustrated_figures(review, ledger)
        state.figures[:] = figures
        return markdown
    if state.presentation in {'comic', 'infographic'}:
        from app.llm.meeting_visual_review import capture_review_visual
        claims = {row['id']: row for row in ledger.claims}
        included = {key: set(row['block_ids']) for key, row in claims.items() if row['disposition'] == 'included'}
        state.visual_review = capture_review_visual(review, claims, included)
    return ledger.markdown


def review_protocol(presentation, *, protocol=4):
    """The model sees the actual envelope, not contradictory core-only rules."""
    presentation = presentation or 'text'
    _need(isinstance(presentation, str) and presentation in _EXTRAS, 'invalid_presentation')
    if protocol == 6:
        _need(type(protocol) is int and presentation in {'comic', 'infographic'}, 'invalid_protocol')
        # Build the new explicit contract from core4 accounting, not raw5 or
        # its projector. Historical 4/5 rules and artifacts stay unchanged.
        lines = review_protocol(presentation).splitlines()
        example = json.loads(lines[1].rstrip('.'))
        example['protocol'] = 6
        for block in example['blocks']:
            block['parts'] = [block.pop('markdown')]
        ref = {'block_id': 'B1', 'part_index': 0, 'claim_ids': ['C1']}
        example['visual'] = ({'protocol': 3, 'scenes': [
            {'id': 'VS1', 'frame_id': '[FRAME:0001]', 'label_ref': ref}], 'diagram': None}
            if presentation == 'comic' else {'protocol': 3, 'scenes': [], 'diagram': {
                'kind': 'cards', 'nodes': [{'id': 'VN1', 'label_ref': ref}], 'edges': []}})
        lines[0] = lines[0].replace('PROTOCOL 4', 'PROTOCOL 6')
        lines[1] = json.dumps(example, ensure_ascii=False, separators=(',', ':')) + '.'
        return '\n'.join(lines).replace('Markdown belongs only inside blocks[].markdown;',
            'Markdown belongs only inside blocks[].parts[] strings;')
    if protocol == 5:
        _need(type(protocol) is int and presentation in {'comic', 'infographic'}, 'invalid_protocol')
        # Reuse all frozen accounting/evidence prose; only explicitly replace
        # the declared body/envelope example, never a legacy raw artifact.
        rules = review_protocol(presentation)
        lines = rules.splitlines()
        example = json.loads(lines[1].rstrip('.'))
        example['protocol'] = 5
        for block in example['blocks']:
            block['parts'] = [{'id': 'P1', 'text': block.pop('markdown')}]
        ref = {'part_id': 'P1', 'claim_ids': ['C1']}
        example['visual'] = ({'protocol': 2, 'scenes': [
            {'id': 'S1', 'frame_id': '[FRAME:0001]', 'label_ref': ref}], 'diagram': None}
            if presentation == 'comic' else {'protocol': 2, 'scenes': [], 'diagram': {
                'kind': 'cards', 'nodes': [{'id': 'N1', 'label_ref': ref}], 'edges': []}})
        lines[0] = lines[0].replace('PROTOCOL 4', 'PROTOCOL 5')
        lines[1] = json.dumps(example, ensure_ascii=False, separators=(',', ':')) + '.'
        return '\n'.join(lines).replace('Markdown belongs only inside blocks[].markdown;',
            'Markdown belongs only inside blocks[].parts[].text;')
    _need(type(protocol) is int and protocol == 4, 'invalid_protocol')
    lines = REVIEW_PROTOCOL.splitlines()
    example = json.loads(lines[1].rstrip('.'))
    if presentation == 'illustrated':
        example['claims'][0]['evidence'].append({'kind': 'frame_observation', 'source_ref': '[FRAME:0001]',
                                               'observation': 'the actual displayed condition'})
        example['figures'] = [{'frame_ref': '[FRAME:0001]', 'claim_ids': ['C1'],
                              'after_block_id': 'B1', 'caption': 'actual displayed condition'}]
        envelope = 'The only top-level fields are protocol, blocks, claims and required figures. Do not output visual.'
    elif presentation in {'comic', 'infographic'}:
        label = example['blocks'][0]['markdown']
        if presentation == 'comic':
            example['claims'][0]['evidence'].append({'kind': 'frame_observation', 'source_ref': '[FRAME:0001]',
                                                   'observation': 'the actual displayed condition'})
            example['visual'] = {'scenes': [{'id': 'S1', 'block_ids': ['B1'], 'frame_id': '[FRAME:0001]',
                                           'grounded_label': label}], 'diagram': None}
        else:
            example['visual'] = {'scenes': [], 'diagram': {'kind': 'cards', 'edges': [],
                'nodes': [{'id': 'N1', 'block_ids': ['B1'], 'grounded_label': label}]}}
        envelope = 'The only top-level fields are protocol, blocks, claims and required visual. Do not output figures.'
    else:
        envelope = 'The only top-level fields are protocol, blocks and claims. Do not output figures or visual.'
    envelope += ' Define and account for claims in the same rows; do not output audit, additional_claims or topic indexes.'
    lines[1] = json.dumps(example, ensure_ascii=False, separators=(',', ':')) + '.'
    return '\n'.join(lines).replace(CORE_ENVELOPE_RULE, envelope)
