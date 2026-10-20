"""Protocol 2: exact source spans, atomic accounting, single-copy report blocks.

This checks provenance and references, never semantic entailment or ASR accuracy.
No provider, artifact writes, repair calls or legacy receipt migration.
"""
import copy
import json
import re

from app.llm.meeting_fact_material import _ids, _require
from app.llm.meeting_presentation import presentation_state
from app.llm.source_references import original_asr_texts
from app.llm.video_material import visual_source_bindings

FIELDS = {'entity', 'relation', 'attribute', 'quantity', 'condition', 'deadline', 'status'}
REJECTIONS = {'unclear_entity', 'unsupported', 'misread', 'incidental', 'non_meeting'}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _evidence(rows):
    _require(isinstance(rows, list) and bool(rows))
    asr, visual = original_asr_texts(), visual_source_bindings()
    result = []
    for row in rows:
        _require(isinstance(row, dict))
        row = dict(row)
        ref, kind = row.get('source_ref'), row.get('kind')
        _require(isinstance(ref, str))
        if kind == 'asr_span':
            raw = asr.get(ref)
        elif kind == 'ocr_span':
            raw = visual.get(ref, {}).get('ocr')
        elif kind == 'frame_observation':
            _require(visual.get(ref, {}).get('image') is True and _text(row.get('observation')))
            row['verification'] = 'model_visual_observation'
            result.append(row)
            continue
        else:
            _require(False)
        quote = row.get('quote')
        _require(isinstance(raw, str) and _text(quote))
        if 'start' in row or 'end' in row:
            start, end = row.get('start'), row.get('end')
            _require(type(start) is int and type(end) is int and 0 <= start < end <= len(raw)
                     and raw[start:end] == quote)
        else:
            start = raw.find(quote)
            _require(start >= 0 and raw.find(quote, start + 1) < 0)
        row['verification'] = 'exact_asr_span' if kind == 'asr_span' else 'exact_ocr_span'
        result.append(row)
    return result


def prepare(value):
    value = copy.deepcopy(value)
    _require(type(value.get('protocol')) is int and value['protocol'] == 2)
    topics = _ids(value.get('topics'), 'id')
    _ids(value.get('facts'), 'id')
    claims = []
    for fact in value['facts']:
        _require(isinstance(fact.get('topic_id'), str) and fact['topic_id'] in topics and 'entity' in fact
                 and (fact['entity'] is None or _text(fact['entity'])))
        _ids(fact.get('claims'), 'id')
        _require(bool(fact['claims']))
        refs = set()
        for claim in fact['claims']:
            _require(isinstance(claim.get('field'), str) and claim['field'] in FIELDS and _text(claim.get('text'))
                     and _text(claim.get('anchor')) and type(claim.get('material')) is bool)
            claim['evidence'] = _evidence(claim.get('evidence'))
            _require(any(claim['anchor'] in (row['observation'] if row['kind'] == 'frame_observation' else row['quote']) for row in claim['evidence']))
            refs.update(row['source_ref'] for row in claim['evidence'])
            claims.append(claim)
        if fact['entity'] is not None:
            _require(any(c['field'] == 'entity' and c['anchor'] == fact['entity'] for c in fact['claims']))
        if 'source_refs' in fact:
            _require(isinstance(fact['source_refs'], list) and all(isinstance(ref, str) for ref in fact['source_refs']) and set(fact['source_refs']) == refs)
        fact['source_refs'] = sorted(refs)  # Derived index, never invented support.
    _ids(claims, 'id')  # Claim IDs are unique across facts.
    return json.dumps(value, ensure_ascii=False)


def _block_ids(row, blocks):
    keys = row.get('block_ids')
    _require(isinstance(keys, list) and all(isinstance(key, str) and key in blocks for key in keys)
             and len(keys) == len(set(keys)))
    return keys


def finalize(value, material):
    _require(type(value.get('protocol')) is int and value['protocol'] == 2)
    material = copy.deepcopy(material)
    for key, addition in [('topics', 'additional_topics'), ('facts', 'additional_facts')]:
        _require(isinstance(material.get(key), list) and isinstance(value.get(addition, []), list))
        material[key].extend(value.get(addition, []))
    material = json.loads(prepare(material))  # Recheck every original and added source binding.
    block_keys = _ids(value.get('blocks'), 'id')
    _require(bool(block_keys))
    blocks = {row['id']: row.get('markdown') for row in value['blocks']}
    _require(all(_text(body) for body in blocks.values()))
    markdown = '\n\n'.join(blocks.values()).strip()
    _require(not re.search(r'\[(?:ASR|FRAME):|!\[|\[\[Screenshot:', markdown))
    claims = {claim['id']: (fact, claim) for fact in material['facts'] for claim in fact['claims']}
    _require(_ids(value.get('audit'), 'claim_id') == set(claims))
    included = {}
    for row in value['audit']:
        fact, claim = claims[row['claim_id']]
        keys = _block_ids(row, blocks)
        disposition = row.get('disposition')
        _require(isinstance(disposition, str) and disposition in {'included', 'rejected', 'omitted_for_depth'})
        if disposition == 'included':
            _require(bool(keys))
            included[row['claim_id']] = set(keys)
        else:
            _require(not keys and _text(row.get('reason')))
            if disposition == 'rejected':
                code = row.get('reason_code')
                _require(isinstance(code, str) and code in REJECTIONS and (code != 'unclear_entity' or claim['field'] == 'entity'))
                evidence = _evidence(row.get('evidence'))
                _require(bool({e['source_ref'] for e in evidence} & {e['source_ref'] for e in claim['evidence']}))
            elif presentation_state() and presentation_state().depth == 'detailed':
                _require(not claim['material'])
    # Optional topic index is never a second copy of the prose.
    if 'topic_audit' in value:
        _require(_ids(value['topic_audit'], 'topic_id') == {t['id'] for t in material['topics']})
        for row in value['topic_audit']:
            keys = _block_ids(row, blocks)
            if not keys:
                _require(_text(row.get('reason')) and not any(f['topic_id'] == row['topic_id'] and key in included for key, (f, _) in claims.items()))
    figures = value.get('figures')
    _require(isinstance(figures, list) and len(figures) <= 8)
    state = presentation_state()
    if not state or state.presentation != 'illustrated':
        _require(not figures)
        return markdown
    _require(bool(figures))
    converted, frames, placements = [], set(), set()
    for figure in figures:
        _require(isinstance(figure, dict))
        ref, ids, block = figure.get('frame_ref'), figure.get('claim_ids'), figure.get('after_block_id')
        _require(isinstance(ref, str) and ref in visual_source_bindings() and ref not in frames
                 and isinstance(ids, list) and bool(ids) and all(isinstance(key, str) and key in included for key in ids))
        _require(isinstance(block, str) and block in blocks and block not in placements
                 and all(block in included[key] and ref in {e['source_ref'] for e in claims[key][1]['evidence']} for key in ids))
        passage, caption = blocks[block], figure.get('caption')
        _require(markdown.count(passage) == 1 and _text(caption) and len(caption) <= 160 and not re.search(r'[\[\]<>\r\n]', caption))
        converted.append({'frame_ref': ref, 'fact_ids': sorted({claims[key][0]['id'] for key in ids}), 'after_passage': passage, 'caption': caption})
        frames.add(ref)
        placements.add(block)
    for figure in converted:
        passage = figure['after_passage']
        markdown = markdown.replace(passage, passage + '\n\n' + figure['frame_ref'], 1)
    state.figures[:] = converted
    return markdown


DRAFT_PROTOCOL = '''AUTOMATIC FACT MATERIAL PROTOCOL 2. Return one JSON object:
{"protocol":2,"topics":[{"id":"T1","title":"source-grounded topic"}],"facts":[{"id":"F1","topic_id":"T1","entity":null,"claims":[{"id":"C1","field":"condition","text":"one independently supported proposition","anchor":"exact source wording","material":true,"evidence":[{"kind":"asr_span","source_ref":"[ASR:0001]","quote":"unique unchanged contiguous excerpt from raw speech"}]}]}]}.
These are schema descriptions, not meeting facts. Field is entity/relation/attribute/quantity/condition/deadline/status. Each claim has a globally unique ID and independently checkable evidence; split uncertain entity identity from clear properties and conditions. entity=null means unknown, not that all properties are unknown. A named entity requires its own entity claim whose anchor exactly equals that name. Each anchor occurs verbatim in at least one evidence quote or visual observation. Do not join neighboring names into a new entity or infer ownership from adjacency.
asr_span quotes are exact raw speech, excluding time labels, speaker timelines and diagnostics; never normalize, repair or translate their spelling, numbers, punctuation or whitespace. Choose a unique contiguous excerpt retaining context. Only if repeated, disambiguate with exact zero-based Python-character start/end offsets into that raw ASR window. References alone do not prove a proposition or the correctness of ASR.
For supplied images use {"kind":"frame_observation","source_ref":"[FRAME:0001]","observation":"what is actually legible or visibly connected"}; this remains fallible model interpretation, never verified OCR. ocr_span uses an exact quote only from actual supplied recognized OCR; unavailable OCR cannot authorize it. Source type must not be switched to make a claim pass. Keep entity, numeric value/configuration/state, conditional and directed relationships separately supported; a clear independent image fact does not require a spoken repetition or a final decision. Never reject a clear property merely because the entity name or spoken cross-reference is unclear.
Keep all original sources in view. No required number of facts, no per-frame fact quota and no full coverage matrix. Empty facts/topics are legal when no substantive proposition remains; never manufacture evidence. The schema must not dictate report sections.'''


REVIEW_PROTOCOL = '''AUTOMATIC FACT REVIEW PROTOCOL 2. Return one JSON object:
{"protocol":2,"blocks":[{"id":"B1","markdown":"one final report paragraph or heading"}],"audit":[{"claim_id":"C1","disposition":"included","block_ids":["B1"]}],"figures":[]}.
Write the report once, in ordered blocks with unique stable IDs of your choice. Audit refers to those IDs, never recopied passages. The program joins block text without displaying IDs. Blocks follow the source topics, with no fixed sections/count. Merged duplicates are included and may share block_ids. Each included claim must retain its actual relation and qualifiers, not an unrelated neighboring paragraph. Complete source review must also restore omissions outside the working list: optional additional_facts/additional_topics use the exact draft schema, with new IDs and validated evidence, and their claims also receive audit rows.
Audit every claim exactly once, never reject an entire fact as one unit. Working material is fallible even when the draft marked material=true. Reconstruct against full original speech and actual images. For a rejected claim use block_ids=[], reason_code=unclear_entity/unsupported/misread/incidental/non_meeting, a specific nonempty reason and evidence in the same source-bound format, including a source of that claim. Bare reasons or references cannot authorize rejection. unclear_entity only rejects an entity claim, never its independent quantity/condition/deadline. Use specific source reasons for non_meeting, incidental or garbled candidates (misread for garbled text). Recheck each attribute separately; correct a wrong candidate without deleting other clear properties. A checked span proves literal presence, not semantic truth; a visual observation is still a model judgment. Do not label important valid content as rejected merely to shorten it.
omitted_for_depth uses block_ids=[] and a selection reason; detailed mode forbids omitting a still-valid material claim for depth. topic_audit is optional; if supplied, each topic occurs once with block_ids or a specific reason when no included claim remains. No internal source IDs, URLs for images, screenshot markers or raw HTML in block text. For illustrated only: figures entries are {frame_ref,claim_ids,after_block_id,caption}; each frame must support those included claims and the exact unique block. No suitable real frame means illustrated is incomplete. No third call, repair call, model substitution or replay.'''
