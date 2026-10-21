"""Input-only draft view; never a replacement material or evidence validator."""
import json

from app.llm.meeting_final_claim_ledger import FinalLedgerError, decode_final_review


def review_draft_input_view(draft: str) -> str:
    value = decode_final_review(draft)
    if (not isinstance(value, dict) or type(value.get('protocol')) is not int
            or value['protocol'] != 3):
        raise FinalLedgerError('invalid_draft_protocol')
    if not isinstance(value.get('claims'), list):
        raise FinalLedgerError('invalid_draft')
    changed = False
    for claim in value['claims']:
        if not isinstance(claim, dict) or not isinstance(claim.get('evidence'), list):
            raise FinalLedgerError('invalid_draft')
        for evidence in claim['evidence']:
            if not isinstance(evidence, dict):
                raise FinalLedgerError('invalid_draft')
            if (evidence.get('kind') in {'asr_span', 'ocr_span'}
                    and evidence.get('verification') == 'unverified'):
                # Host prepare already checked this span. Do not expose its
                # unmatched quotation/offsets as text for the reviewer to echo.
                for key in ('quote', 'start', 'end'):
                    evidence.pop(key, None)
                changed = True
                continue
            if evidence.get('kind') != 'frame_observation':
                continue
            observation = evidence.get('observation')
            if (not isinstance(observation, str) or not observation.strip()
                    or not isinstance(evidence.get('source_ref'), str)
                    or not evidence['source_ref']):
                raise FinalLedgerError('invalid_draft')
            del evidence['observation']
            if evidence.get('verification') == 'model_visual_observation':
                del evidence['verification']
            changed = True
    if not changed:
        return draft
    # This wrapper is deliberately not a protocol-3 material. The host keeps
    # the complete prepared original and passes only that original to guards.
    del value['protocol']
    return json.dumps({'original_claims_view': value}, ensure_ascii=False)
