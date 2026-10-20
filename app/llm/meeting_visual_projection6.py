"""Explicit final/6 -> ledger/4 and bound-visual/1, with no I/O or repair.

Parts are the sole reader-facing text. Labels select an entire string by path;
claim text is never a label source. Readback uses this same pure projection.
Independent P6 implementation: never fabricate raw5 or invoke the P5 projector.
Only part naming is removed; other ID, source and visibility rules remain.
Literal/source binding is not semantic entailment or execution authority.
"""
import copy
import re

from app.llm.meeting_final_claim_ledger import FinalLedgerError
from app.llm.meeting_markdown import _parse


_ID = re.compile(r'[A-Za-z0-9_\[\]:.\-]{1,64}\Z')


def _need(condition, code='invalid_visual_reference'):
    if not condition:
        raise FinalLedgerError(code)


def _object(value, keys):
    _need(type(value) is dict and set(value) == set(keys))


def _rows(value, maximum, minimum=0):
    _need(type(value) is list and minimum <= len(value) <= maximum)


def core_review6(value):
    """Validate new text shape, preserving every part byte-for-character."""
    _object(value, {'protocol', 'blocks', 'claims', 'visual'})
    _need(type(value['protocol']) is int and value['protocol'] == 6, 'invalid_protocol')
    _rows(value['blocks'], 64, 1)
    _need(type(value['claims']) is list)
    seen, blocks, count = set(), [], 0

    def identity(key):
        _need(isinstance(key, str) and _ID.fullmatch(key) and key not in seen,
              'invalid_visual_reference_ids')
        seen.add(key)

    for block in value['blocks']:
        _object(block, {'id', 'parts'})
        identity(block['id'])
        _rows(block['parts'], 128, 1)
        text = []
        for part in block['parts']:
            count += 1
            _need(count <= 512 and isinstance(part, str) and bool(part)
                  and len(part) <= 6000 and '\r' not in part)
            text.append(part)
        joined = ''.join(text)
        _need(bool(joined.strip()) and len(joined) <= 6000)
        blocks.append({'id': block['id'], 'markdown': joined})
    for claim in value['claims']:
        _need(type(claim) is dict)
        identity(claim.get('id'))
    plan = value['visual']
    _object(plan, {'protocol', 'scenes', 'diagram'})
    _need(type(plan['protocol']) is int and plan['protocol'] == 3)
    _rows(plan['scenes'], 8)
    for row in plan['scenes']:
        _need(type(row) is dict)
        identity(row.get('id'))
    if plan['diagram'] is not None:
        _object(plan['diagram'], {'kind', 'nodes', 'edges'})
        _rows(plan['diagram']['nodes'], 12, 1)
        _rows(plan['diagram']['edges'], 20)
        for row in plan['diagram']['nodes'] + plan['diagram']['edges']:
            _need(type(row) is dict)
            identity(row.get('id'))
    return {'protocol': 4, 'blocks': blocks, 'claims': copy.deepcopy(value['claims'])}


def project_review6(value, *, presentation):
    """Rebuild exact v1 plan; first execution must ALSO validate core ledger.

    Historical reads repeat deterministic structure/equality, never source
    dispatch or a fresh claim audit. Accepted receipts and raw hash remain the
    caller's separate provenance gates.
    """
    _need(presentation in {'comic', 'infographic'}, 'invalid_presentation')
    core = core_review6(value)
    blocks = {row['id']: row['markdown'] for row in core['blocks']}
    parts = {block['id']: block['parts'] for block in value['blocks']}
    claims = {}
    required = {'id', 'field', 'text', 'material', 'disposition', 'block_ids', 'evidence'}
    for row in core['claims']:
        _need(required <= set(row) <= required | {'reason', 'reason_code'})
        _need(isinstance(row['field'], str) and bool(row['field'].strip())
              and isinstance(row['text'], str) and bool(row['text'].strip())
              and type(row['material']) is bool and type(row['evidence']) is list)
        ids = row['block_ids']
        _rows(ids, 64)
        _need(all(isinstance(key, str) and key in blocks for key in ids) and len(ids) == len(set(ids)))
        _need(isinstance(row['disposition'], str)
              and row['disposition'] in {'included', 'rejected', 'omitted_for_depth'})
        if row['disposition'] == 'included':
            _need(bool(ids) and bool(row['evidence']))
            claims[row['id']] = row
        else:
            _need(not ids)
    joined = '\n\n'.join(row['markdown'] for row in core['blocks'])
    markdown = joined.strip()
    # Prove the exact occurrence by its known joined-body offset, never find().
    # The whole selected block must be one unchanged top-level plain paragraph.
    # This excludes fences spanning blocks, definitions, escapes, entities,
    # headings, links and other syntax that could hide/transform the chosen text.
    try:
        tokens = _parse(markdown)
    except ValueError:
        raise FinalLedgerError('invalid_visual_reference_visibility') from None
    visible, offset = set(), len(joined.lstrip()) - len(joined)
    for row in core['blocks']:
        text = row['markdown']
        if text == text.strip() and '\n' not in text and not re.search(r'[\x00-\x1f\x7f]', text):
            line = markdown[:offset].count('\n')
            for index, token in enumerate(tokens):
                if (index and token.type == 'inline' and token.map == [line, line + 1]
                        and token.content == text and tokens[index - 1].type == 'paragraph_open'
                        and tokens[index - 1].level == 0 and len(token.children or []) == 1
                        and token.children[0].type == 'text' and token.children[0].content == text):
                    visible.add(row['id'])
        offset += len(text) + 2

    def label(ref):
        _object(ref, {'block_id', 'part_index', 'claim_ids'})
        block, index = ref['block_id'], ref['part_index']
        _need(isinstance(block, str) and block in parts
              and type(index) is int and 0 <= index < len(parts[block]),
              'invalid_visual_reference_path')
        text = parts[block][index]
        ids = ref['claim_ids']
        _rows(ids, 64, 1)
        _need(all(isinstance(key, str) and key in claims and block in claims[key]['block_ids'] for key in ids)
              and len(ids) == len(set(ids)))
        _need(block in visible, 'invalid_visual_reference_visibility')
        _need(bool(text.strip()) and len(text) <= 120 and not re.search(r'[\x00-\x1f\x7f]', text),
              'invalid_visual_reference_label')
        return block, text, ids

    plan = value['visual']
    scenes = []
    for row in plan['scenes']:
        _object(row, {'id', 'frame_id', 'label_ref'})
        block, text, ids = label(row['label_ref'])
        frame = row['frame_id']
        _need(isinstance(frame, str) and re.fullmatch(r'\[FRAME:[0-9]{4,}\]', frame))
        for key in ids:
            _need(any(type(e) is dict and e.get('kind') in {'ocr_span', 'frame_observation'}
                      and e.get('source_ref') == frame for e in claims[key]['evidence']),
                  'invalid_visual_reference_frame')
        scenes.append({'id': row['id'], 'frame_id': frame, 'block_ids': [block], 'grounded_label': text})
    diagram = None
    if presentation == 'comic':
        _need(bool(scenes) and plan['diagram'] is None)
    else:
        _need(not scenes and type(plan['diagram']) is dict)
        source = plan['diagram']
        _need(isinstance(source['kind'], str) and source['kind'] in {'cards', 'comparison', 'flow', 'relationship'})
        nodes, edges = [], []
        for row in source['nodes']:
            _object(row, {'id', 'label_ref'})
            block, text, _ = label(row['label_ref'])
            nodes.append({'id': row['id'], 'block_ids': [block], 'grounded_label': text})
        node_ids = {row['id'] for row in nodes}
        for row in source['edges']:
            _object(row, {'id', 'from', 'to', 'label_ref'})
            _need(isinstance(row['from'], str) and row['from'] in node_ids
                  and isinstance(row['to'], str) and row['to'] in node_ids)
            block, text, _ = label(row['label_ref'])
            edges.append({'id': row['id'], 'from': row['from'], 'to': row['to'],
                          'block_ids': [block], 'grounded_label': text})
        _need(not edges if source['kind'] in {'cards', 'comparison'} else bool(edges))
        diagram = {'kind': source['kind'], 'nodes': nodes, 'edges': edges}
    return core, {'scenes': scenes, 'diagram': diagram}


PARTS_RULE6 = '''FINAL/6 STRING PARTS AND VISUAL-REF/3.
Write reader-facing text once, only in blocks[].parts[] strings. Each block is {"id":"B1","parts":["one reviewed paragraph"]}. Concatenate strings EXACTLY with no inserted separator to obtain that block's Markdown; use a separate block when a heading or paragraph needs its own boundary. The final body joins blocks with two LF and strips only the whole body's outside whitespace. Use LF, never CR. Keep existing claims/accounting/evidence rules, linking claims to block IDs. All block/claim/scene/node/edge IDs retain their global uniqueness; parts have NO IDs. At most 64 blocks, 128 strings per block, 512 strings total; each joined block at most 6000 characters.
Graphic labels use only label_ref={"block_id":"B1","part_index":0,"claim_ids":["C1"]}. part_index is a zero-based integer array index within that exact block, never a string, boolean, float, negative index or omitted default. Host selects the WHOLE original string at that path; it never copies claim.text, searches matching text, shortens, repairs, concatenates quotes or infers scope from claims. Every cited claim must be included and link to that exact block. Selected strings are 1-120 Unicode code points, no C0/DEL controls or newlines. The entire selected block must be a single-line top-level plain paragraph without surrounding whitespace or Markdown syntax that hides/transforms text. Unselected blocks may use supported Markdown. Preserve complete objects, conditions, negation and status; omit unsuitable selections rather than discard essential qualifiers. An overlong paragraph is not a valid label and is never truncated. Exact references prove literal presence, not semantic truth. Do not add prose merely to provide labels.
The only visual fields are protocol/scenes/diagram; visual.protocol=3. Follow ONLY the requested presentation's nonempty valid example below. Never output grounded_label, part_id, a second block_ids list or free label text. Never return HTML/SVG/code, coordinates, image data or resource paths in visual fields. No figures field, other format, extra model call or automatic repair. Whole-source review is independent of the selected graphic subset.'''

COMIC_RULE6 = '''Presentation: real recording storyboard, not invented illustrations.
Return visual={"protocol":3,"scenes":[{"id":"S1","frame_id":"[FRAME:0001]","label_ref":{"block_id":"B1","part_index":0,"claim_ids":["C1"]}}],"diagram":null}. Use 1-8 relevant scenes; empty scenes means incomplete. Each cited included claim's OWN effective evidence must contain that exact actual supplied frame; neighboring claims or time overlap cannot lend evidence. Read the actual images and context; never select opening frames, defaults or decorative pictures just to fill a quota. No relevant supplied frame means incomplete, never invent a picture or change format/model.'''

INFO_RULE6 = '''Presentation: substantive information diagram rendered on-device from reviewed facts.
Return visual={"protocol":3,"scenes":[],"diagram":{"kind":"cards","nodes":[{"id":"N1","label_ref":{"block_id":"B1","part_index":0,"claim_ids":["C1"]}}],"edges":[]}}. diagram must be an object, not null. Use 1-12 nodes and at most 20 edges; an edge is {"id":"E1","from":"N1","to":"N2","label_ref":{"block_id":"B2","part_index":0,"claim_ids":["C2"]}}. Both endpoints must exist. Choose cards/comparison/flow/relationship from substantive content, never a fixed template. Cards/comparison have no edges; flow/relationship require a source-supported edge. Select the smallest structure explaining an important relationship, meaningful alternatives or explicit process, not a table of contents. Never split an object and its values across independent nodes. Check the complete source -> relation -> target proposition, direction, conditions and status against original evidence and selected text; proximity never supplies a relation. Remove redundant nodes and omit unsuitable excerpts rather than lose qualifiers, expand prose for labels, or manufacture an edge.'''
