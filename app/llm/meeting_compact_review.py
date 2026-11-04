"""Protocol 8: explicit unchanged decisions over immutable draft claims.

Only the wire representation is compact. Expansion is detached and goes through
the same complete protocol-4 source/identity/depth checks. Raw responses remain
unchanged; this module does not repair JSON or infer a review decision.
"""
import copy

from app.llm.meeting_final_claim_ledger import FinalLedgerError, validate_final_ledger


def _need(condition):
    if not condition:
        raise FinalLedgerError('invalid_compact_review')


def validate_compact_review(value, material, *, depth):
    _need(type(value) is dict and set(value) == {'protocol', 'blocks', 'claims'}
          and type(value['protocol']) is int and value['protocol'] == 8
          and type(value['claims']) is list)
    _need(type(material) is dict and material.get('protocol') == 3
          and type(material.get('claims')) is list)
    original = {}
    for row in material['claims']:
        _need(type(row) is dict and isinstance(row.get('id'), str)
              and row['id'] not in original)
        original[row['id']] = row
    claims = []
    for row in value['claims']:
        _need(type(row) is dict)
        if 'unchanged' not in row:
            claims.append(copy.deepcopy(row))
            continue
        _need(row['unchanged'] is True and isinstance(row.get('id'), str)
              and row['id'] in original)
        disposition = row.get('disposition')
        _need(disposition in ('included', 'omitted_for_depth'))
        keys = {'id', 'unchanged', 'disposition', 'block_ids'}
        if disposition == 'omitted_for_depth':
            keys.add('reason')
        _need(set(row) == keys)
        candidate = original[row['id']]
        evidence = candidate.get('evidence')
        # A visual interpretation or known invalid draft span must be reviewed
        # explicitly, never silently adopted by a compact confirmation.
        _need(isinstance(evidence, list) and bool(evidence) and all(
            isinstance(item, dict) and item.get('kind') in ('asr_span', 'ocr_span')
            and item.get('verification') != 'unverified' for item in evidence))
        expanded = {key: copy.deepcopy(candidate.get(key))
                    for key in ('id', 'field', 'text', 'material', 'evidence')}
        expanded.update({key: copy.deepcopy(item) for key, item in row.items() if key != 'unchanged'})
        claims.append(expanded)
    return validate_final_ledger({'protocol': 4, 'blocks': copy.deepcopy(value['blocks']),
                                  'claims': claims}, material, depth=depth)


def compact_review_protocol():
    # Keep the established evidence semantics, replace only the wire row rules.
    from app.llm.meeting_final_claim_ledger import REVIEW_PROTOCOL
    rules = REVIEW_PROTOCOL.replace('PROTOCOL 4', 'PROTOCOL 8').replace('"protocol":4', '"protocol":8')
    rules = rules.replace('Each row requires id/field/text/material/disposition/block_ids/evidence.',
                          'Each full row requires id/field/text/material/disposition/block_ids/evidence.')
    rules = rules.replace('Explicitly provide the effective evidence, including for original claims;',
                          'For a full row explicitly provide the effective evidence, including for original claims;')
    rules = rules.replace('Every omitted_for_depth row must explicitly include the evidence key:',
                          'Every full omitted_for_depth row must explicitly include the evidence key:')
    rules = rules.replace('Included requires at least one real block ID and a complete valid final evidence list.',
                          'After host expansion, every included claim requires at least one real block ID and a complete valid final evidence list. Compact unchanged rows omit the evidence key on the wire because the host copies the explicitly confirmed frozen evidence; full rows supply it explicitly.')
    rules = rules.replace('Never omit the key or invent support;',
                          'Full rows must never omit the evidence key or invent support;')
    compact_rules = '''
COMPACT ORIGINAL CONFIRMATIONS (protocol 8). Prefer this short row after independently checking an original claim against the COMPLETE source: {"id":"C1","unchanged":true,"disposition":"included","block_ids":["B1"]}. This explicitly confirms that the original text, field, material and entire ASR/OCR evidence list are correct WITHOUT ANY CHANGE. The host uses exactly those frozen values and checks the source spans again. Do not repeat them in that row. Use this only when all original evidence is valid asr_span/ocr_span, never verification=unverified, missing quotes, or frame_observation. Do not use it to avoid examining the source or to accept a mistaken relationship. The linked final prose must preserve the original proposition and its qualifiers, though it may consolidate duplicates naturally.
For a valid original omitted at brief/concise depth, the compact row is {"id":"C1","unchanged":true,"disposition":"omitted_for_depth","block_ids":[],"reason":"specific depth-selection reason"}. Detailed material=true still cannot be omitted. Each original ID must occur once. Changed text/evidence, rejections and new claims MUST use the full row shape above, with no unchanged key. Never mix unchanged with override fields. No implicit confirmation, missing row, or partial response is accepted. This reduces repeated serialization only; input remains the whole original meeting and the complete draft. Write the actual report only once in blocks, with # title and ## topic headings, not in a second report field.'''
    compact_rules = compact_rules.replace('full row shape above', 'full row shape below')
    heading, rest = rules.split('\n', 1)
    return heading + compact_rules + '\nFULL-ROW ENVELOPE EXAMPLE AND SHARED VALIDATION RULES:\n' + rest
