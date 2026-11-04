"""Strictly validate and merge independently reviewed subsets of a frozen draft."""
import copy

from app.llm.meeting_final_claim_ledger import FinalLedgerError, validate_final_ledger


def merge_batches(draft, batches, *, depth):
    original_ids = {row['id'] for row in draft['claims']}
    seen_original = set()
    merged = {'protocol': 4, 'claims': [], 'blocks': []}
    for index, (claims, value) in enumerate(batches):
        subset = {**draft, 'claims': claims}
        allowed = {row['id'] for row in claims}
        if seen_original & allowed:
            raise FinalLedgerError('duplicate_batch_claims')
        seen_original |= allowed
        validate_final_ledger(value, subset, depth=depth)
        rows = copy.deepcopy(value['claims'])
        blocks = copy.deepcopy(value['blocks'])
        if any(row['id'] in original_ids - allowed for row in rows):
            raise FinalLedgerError('foreign_batch_claim')
        mapping = {row['id']: f'batch{index + 1}:{row["id"]}' for row in blocks}
        for row in blocks:
            row['id'] = mapping[row['id']]
        for row in rows:
            if row['id'] not in allowed:
                row['id'] = f'batch{index + 1}:new:{row["id"]}'
                if row['id'] in original_ids:
                    raise FinalLedgerError('duplicate_batch_claims')
            row['block_ids'] = [mapping[key] for key in row['block_ids']]
        merged['claims'].extend(rows)
        merged['blocks'].extend(blocks)
    if seen_original != original_ids:
        raise FinalLedgerError('missing_original_claims')
    validate_final_ledger(merged, draft, depth=depth)
    return merged
