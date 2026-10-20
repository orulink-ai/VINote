"""Private proposed final/7 projection. No I/O, execution grant or source repair.

Only blocks.parts contain published prose. Included rows locate one exact part;
excluded rows retain their unpublished candidate text. Existing ledger/4 checks
and visual/6 checks are reused on detached internal values, never saved as raw.
"""
import copy
import re

from app.llm.meeting_final_claim_ledger import FinalLedgerError, validate_final_ledger
from app.llm.meeting_visual_projection6 import project_review6
from app.llm.meeting_markdown import _parse


_ID = re.compile(r'[A-Za-z0-9_\[\]:.\-]{1,64}\Z')
_EXTRAS = {'comic': {'visual'}, 'infographic': {'visual'}}


def _need(condition, code):
    if not condition:
        raise FinalLedgerError(code)


def core_review7(value, *, presentation):
    """Return detached core/4 with text/block_ids derived, never model-repeated.

    Every part must have included coverage. This is literal accounting, not
    proof of entailment, importance or source coverage. Every part must also
    occupy its exact visible characters in a plain paragraph of the joined body.
    First execution must additionally call validate_review7 with frozen sources.
    """
    _need(isinstance(presentation, str) and presentation in {'comic', 'infographic'}, 'invalid_presentation')
    _need(type(value) is dict and set(value) == {'protocol', 'blocks', 'claims', 'title_ref'} | _EXTRAS[presentation],
          'invalid_single_copy_envelope')
    _need(type(value['protocol']) is int and value['protocol'] == 7, 'invalid_protocol')
    _need(type(value['blocks']) is list and 1 <= len(value['blocks']) <= 64, 'invalid_blocks')
    _need(type(value['claims']) is list, 'invalid_claim_ids')
    seen, parts, blocks = set(), {}, []

    def identity(key):
        _need(isinstance(key, str) and _ID.fullmatch(key) is not None and key not in seen,
              'invalid_single_copy_ids')
        seen.add(key)

    for block in value['blocks']:
        _need(type(block) is dict and set(block) == {'id', 'parts'}, 'invalid_blocks')
        identity(block['id'])
        strings = block['parts']
        _need(type(strings) is list and 1 <= len(strings) <= 128, 'invalid_blocks')
        for index, text in enumerate(strings):
            _need(isinstance(text, str) and bool(text.strip()) and len(text) <= 6000
                  and '\r' not in text, 'invalid_blocks')
            parts[(block['id'], index)] = text
        _need(len(parts) <= 512, 'invalid_blocks')
        joined = ''.join(strings)
        _need(len(joined) <= 6000, 'invalid_blocks')
        blocks.append({'id': block['id'], 'markdown': joined})

    claims, used = [], set()
    base = {'id', 'field', 'material', 'disposition', 'evidence'}
    for claim in value['claims']:
        _need(type(claim) is dict and base <= set(claim), 'invalid_claim_shape')
        identity(claim['id'])
        _need(isinstance(claim['field'], str) and bool(claim['field'].strip())
              and type(claim['material']) is bool and type(claim['evidence']) is list,
              'invalid_claim_shape')
        disposition = claim['disposition']
        _need(isinstance(disposition, str)
              and disposition in {'included', 'rejected', 'omitted_for_depth'}, 'invalid_disposition')
        row = copy.deepcopy(claim)
        if disposition == 'included':
            _need(set(claim) == base | {'part_ref'}, 'invalid_claim_shape')
            ref = claim['part_ref']
            _need(type(ref) is dict and set(ref) == {'block_id', 'part_index'}, 'invalid_claim_part')
            block, index = ref['block_id'], ref['part_index']
            _need(isinstance(block, str) and type(index) is int and (block, index) in parts,
                  'invalid_claim_part')
            used.add((block, index))
            row.pop('part_ref')
            row['text'], row['block_ids'] = parts[(block, index)], [block]
        else:
            required = base | {'text', 'reason'}
            if disposition == 'rejected':
                required |= {'reason_code'}
            _need(set(claim) == required and isinstance(claim['text'], str)
                  and bool(claim['text'].strip()) and isinstance(claim['reason'], str)
                  and bool(claim['reason'].strip()), 'invalid_exclusion')
            row['block_ids'] = []
        claims.append(row)
    _need(used == set(parts), 'unreferenced_body_part')
    core = {'protocol': 4, 'blocks': blocks, 'claims': claims}
    _visible_part_ranges7(value, core)
    _title_part7(value, parts, used)
    return core


def project_review7(value, *, presentation):
    """Pure readback projection, not a substitute for first-execution guards.

    The temporary visual/6 value is never persisted or returned as raw. Reusing
    its existing shape/visibility/limits preserves those guards unchanged; P7
    additionally requires every graphic claim to cite the very same part.
    """
    core = core_review7(value, presentation=presentation)
    detached = {'protocol': 6, 'blocks': copy.deepcopy(value['blocks']),
                'claims': copy.deepcopy(core['claims']), 'visual': copy.deepcopy(value['visual'])}
    _, plan = project_review6(detached, presentation=presentation)
    claims = {row['id']: row for row in value['claims']}
    visual = value['visual']
    entries = list(visual['scenes'])
    if visual['diagram'] is not None:
        entries += visual['diagram']['nodes'] + visual['diagram']['edges']
    for entry in entries:
        ref = entry['label_ref']
        path = {'block_id': ref['block_id'], 'part_index': ref['part_index']}
        _need(all(claims[key].get('part_ref') == path for key in ref['claim_ids']),
              'invalid_visual_claim_part')
    return core, plan


def validate_review7(value, material, *, depth, presentation):
    """First-execution ledger guard; ASR/OCR quotes are never normalized."""
    core, _ = project_review7(value, presentation=presentation)
    ledger = validate_final_ledger(core, material, depth=depth)
    return ledger


def _visible_part_ranges7(value, core):
    """Prove ALL part intervals, not only graphic-selected part visibility.

    The entire joined body is parsed once. Each block must correspond exactly
    to one top-level single-line paragraph with one unchanged text child. Its
    line is derived from the known cumulative body offset, never find() or a
    matching occurrence elsewhere. Thus no Markdown syntax can hide or change
    a substring within an accepted block. Unicode offsets use Python characters.
    This is literal parser visibility, not a claim about native pixel rendering.
    """
    joined = '\n\n'.join(block['markdown'] for block in core['blocks'])
    try:
        tokens = _parse(joined)
    except ValueError:
        raise FinalLedgerError('invalid_body_part_visibility') from None
    offset, ranges = 0, {}
    for original, block in zip(value['blocks'], core['blocks']):
        text = block['markdown']
        _need(text == text.strip() and not re.search(r'[\x00-\x1f\x7f]', text),
              'invalid_body_part_visibility')
        line = joined[:offset].count('\n')
        _need(any(index > 0 and token.type == 'inline' and token.map == [line, line + 1]
                  and token.content == text and tokens[index - 1].type == 'paragraph_open'
                  and tokens[index - 1].level == 0 and len(token.children or []) == 1
                  and token.children[0].type == 'text' and token.children[0].content == text
                  for index, token in enumerate(tokens)), 'invalid_body_part_visibility')
        position = offset
        for index, part in enumerate(original['parts']):
            end = position + len(part)
            _need(offset <= position < end <= offset + len(text)
                  and joined[position:end] == part, 'invalid_body_part_visibility')
            ranges[(block['id'], index)] = (position, end)
            position = end
        _need(position == offset + len(text), 'invalid_body_part_visibility')
        offset = position + 2
    return ranges


def review_protocol7(presentation):
    """Explicit new shape only; old protocol prompt bytes remain untouched."""
    import json
    from app.llm.meeting_final_claim_ledger import REVIEW_PROTOCOL
    _need(presentation in {'comic', 'infographic'}, 'invalid_protocol')
    claim = {'id': 'C1', 'field': 'condition', 'material': True, 'disposition': 'included',
             'part_ref': {'block_id': 'B1', 'part_index': 0},
             'evidence': [{'kind': 'asr_span', 'source_ref': '[ASR:0001]', 'quote': 'unchanged source clause'}]}
    ref = {'block_id': 'B1', 'part_index': 0, 'claim_ids': ['C1']}
    visual = ({'protocol': 3, 'scenes': [{'id': 'VS1', 'frame_id': '[FRAME:0001]', 'label_ref': ref}], 'diagram': None}
              if presentation == 'comic' else {'protocol': 3, 'scenes': [], 'diagram': {
                  'kind': 'cards', 'nodes': [{'id': 'VN1', 'label_ref': ref}], 'edges': []}})
    if presentation == 'comic':
        claim['evidence'].append({'kind': 'frame_observation', 'source_ref': '[FRAME:0001]',
                                  'observation': 'the actual displayed condition'})
    example = {'protocol': 7, 'claims': [claim], 'blocks': [
        {'id': 'B1', 'parts': ['one complete reviewed factual paragraph']}],
        'title_ref': {'block_id': 'B1', 'part_index': 0}, 'visual': visual}
    lines = REVIEW_PROTOCOL.splitlines()
    # Preserve the source/evidence and complete-original review paragraphs
    # verbatim. Replace only the incompatible declaration/accounting shapes.
    return '\n'.join([
        'FINAL CLAIM LEDGER PROTOCOL 7. Return exactly one JSON object, without a code fence or surrounding prose:',
        json.dumps(example, ensure_ascii=False, separators=(',', ':')) + '.',
        'This is a schema example, not meeting facts. The only top-level fields are protocol, claims, blocks, required title_ref and required visual. No audit, additional_claims, topic indexes or figures.',
        'Fictional routing illustration, not report content: BX.parts=["Only after inspection, the library sends a book to the bindery."," Only after repair, the bindery sends the book to the archive."]. The input library -> bindery uses included claim CX and label_ref {"block_id":"BX","part_index":0,"claim_ids":["CX"]}, preserving inspection; the output bindery -> archive uses CY and {"block_id":"BX","part_index":1,"claim_ids":["CY"]}, preserving repair. Each claim\'s part_ref has that same block_id/part_index.',
        'Complete claims before blocks; their part_ref locates the exact whole original part in the report blocks that follow. Then write the reader-facing report ONCE in blocks[].parts[] strings. Each whole block is one complete single-line plain factual paragraph. No separate headings, Markdown formatting, HTML, images, screenshot placeholders or internal ASR/FRAME IDs in these strings. No fixed sections or paragraph counts. Use the requested output language for the report and unpublished candidate text; evidence quotes retain source spelling and language.',
        "Every original draft claim ID must appear exactly once, including rejected/omitted claims. Preserve each original ID, field and boolean material flag. Correct its proposition in the referenced body part and its own evidence against the complete original source. Do not renumber, relabel or lower material. Different claims may reference the same whole part when it actually covers them. New propositions use globally unique IDs and the same disposition-specific shape. Define and account for each proposition together.",
        'Included row fields are exactly id/field/material/disposition/evidence/part_ref. part_ref={"block_id":"B1","part_index":0}; do not output included text or block_ids. Every paragraph part must have an included claim referencing that exact position. Provide the complete effective final evidence for each included claim, replacing mistaken draft evidence rather than merging it. Draft verification=unverified is not proof. Rejected rows instead require id/field/text/material/disposition/evidence/reason/reason_code and have no part_ref/block_ids. Their text is the unpublished candidate, not extra report prose. reason_code is unclear_entity/unsupported/misread/incidental/non_meeting, with a specific reason and valid actual-source evidence; unclear_entity only applies to entity claims. Rejection is not a way to shorten supported important content.',
        'omitted_for_depth rows instead require id/field/text/material/disposition/evidence/reason, with no part_ref/block_ids. Their text is unpublished candidate context. Detailed output cannot omit a material=true claim for depth, including a new claim. An omitted row may use evidence=[] rather than invent support; any supplied evidence must be valid. Working material remains fallible; use source-grounded rejection reasons for genuinely mistaken candidates, never disguise a real omission as rejection. Unknown owner, missing final decision or uncertain outcome alone does not reject a supported request, proposal or condition.',
        'title_ref={"block_id":"B1","part_index":0} is required and selects one WHOLE already-included visible body part, 1–120 Unicode code points. It supplies the metadata topic, not another prose slot. Do not output free title or heading text, select a substring, cross parts, trim or rely on host truncation. Choose a relevant complete supported part; no new fact or paragraph is needed merely to supply a title.',
        lines[7],  # Exact existing ASR/OCR/frame-evidence rule, never normalized.
        lines[8],  # Exact complete-source review and semantic responsibility.
    ])


def visual_instructions7(presentation):
    from app.llm.meeting_visual_projection6 import COMIC_RULE6, INFO_RULE6
    _need(presentation in {'comic', 'infographic'}, 'invalid_protocol')
    layout = COMIC_RULE6 if presentation == 'comic' else INFO_RULE6
    for original, prefixed in (('S1', 'VS1'), ('N1', 'VN1'), ('N2', 'VN2'), ('E1', 'VE1')):
        layout = layout.replace('"' + original + '"', '"' + prefixed + '"')
    return ('\nFINAL/7 SINGLE-COPY PARTS AND VISUAL-REF/3.\n'
            'blocks have id/parts; parts are nonempty strings, concatenated EXACTLY without an inserted separator. Blocks join with two LF; strip only the whole body outside boundary. Use LF, no CR. All blocks must be whole plain single-line top-level paragraphs, with no hidden or transformed Markdown parts. At most 64 blocks, 128 parts per block, 512 parts total, 6000 characters per block. Each included part_ref has a real block_id and strict zero-based integer part_index, not bool/string/float/negative or an omitted default. All block/claim/scene/node/edge IDs remain globally unique.\n'
            'Every graphic label_ref={"block_id":"B1","part_index":0,"claim_ids":["C1"]} selects the WHOLE string at that exact path. Every listed included claim must have that very same part_ref and its own evidence. No cross-part or neighboring-claim/frame borrowing. No free label, grounded_label, part_id, block_ids or second text copy. Labels are 1–120 Unicode code points without controls/newlines, never truncated; do not discard a qualifier or enlarge prose merely to supply a label. Whole-source body review is independent of the selected graphic subset.\n'
            + layout)


def _title_part7(value, parts, used):
    ref = value['title_ref']
    _need(type(ref) is dict and set(ref) == {'block_id', 'part_index'}, 'invalid_title_reference')
    block, index = ref['block_id'], ref['part_index']
    _need(isinstance(block, str) and type(index) is int and (block, index) in parts
          and (block, index) in used, 'invalid_title_reference')
    text = parts[(block, index)]
    _need(1 <= len(text) <= 120 and not re.search(r'[\x00-\x1f\x7f]', text), 'invalid_title_reference')
    return text


def reviewed_title7(value, *, presentation):
    core_review7(value, presentation=presentation)
    parts = {(b['id'], i): part for b in value['blocks'] for i, part in enumerate(b['parts'])}
    used = {(row['part_ref']['block_id'], row['part_ref']['part_index'])
            for row in value['claims'] if row['disposition'] == 'included'}
    return _title_part7(value, parts, used)


def metadata_title7(value, *, presentation, source_title):
    """Exact selected topic plus the pre-existing literal source-time policy.

    This does not infer a capture/meeting date, search a different part, trim
    the topic, modify source metadata, or set any user-edited saved note title.
    """
    _need(isinstance(source_title, str), 'invalid_source_title')
    topic = reviewed_title7(value, presentation=presentation)
    source_time = re.match(r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*[|｜]', source_title or '')
    return (f'{source_time.group(1)} | {topic}'
            if source_time and not topic.startswith(source_time.group(1)) else topic)
