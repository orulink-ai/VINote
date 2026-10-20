"""Validate automatic fact organization and review accounting, not factual truth.

The complete original source remains in both calls. No additional inference,
answer key, repair call, model substitution or partial-result fallback.
"""
import json
import re
from app.llm.meeting_presentation import presentation_state


def supplied_refs(source):
    from app.llm.video_material import video_reference_ids
    return set(re.findall(r'\[(?:ASR|FRAME):\d{4,}\]', source)) | set(video_reference_ids())


def _json(text):
    text = text.strip()
    if text.startswith('```json') and text.endswith('```'):
        text = text[7:-3].strip()
    try:
        value = json.loads(text)
        if not isinstance(value, dict): raise ValueError()
        return value
    except (ValueError, TypeError):
        raise ValueError('模型未返回完整的事实核对结构，未将部分结果保存为完成稿') from None


def _require(condition):
    if not condition:
        raise ValueError('事实关系或覆盖核对结构不完整，未保存为完成稿')


def _ids(rows, key):
    _require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows))
    values = [row.get(key) for row in rows]
    _require(all(isinstance(value, str) and value for value in values) and len(set(values)) == len(values))
    return set(values)


def _proof_quote_text(text):
    """Normalize layout only; retain Latin word and numeric token boundaries.

    CJK text can wrap without a word separator. Do not remove all whitespace:
    that would conflate identifiers or decimals. Fact and topic proofs share
    this policy; exact/unique illustration placement never uses it.
    """
    text = re.sub(r'\s+', ' ', text).strip()
    cjk = r'\u3400-\u9fff\uf900-\ufaff。！？；，、'
    return re.sub(rf'(?<=[{cjk}]) (?=[{cjk}])', '', text)


COVERAGE_RULE = ('\nCoverage fact_ids are navigation suggestions for independent review, '
    'not evidence edges. They need not mirror fact.source_refs. Only a fact\'s '
    'actual source_refs identify its claimed support; independently check that '
    'material and the rest of the complete original source. Never add a support '
    'reference merely to make a coverage map symmetric, or trust a coverage link '
    'as proof of a fact or relationship.')


MATERIALITY_RULE = '''\nSOURCE RELEVANCE BEFORE OUTPUT DEPTH.
The working facts and their material flags are fallible candidate interpretations, never independent evidence or a requirement to include everything. materiality is not certainty: an important proposal, comparison, explicit request, conditional arrangement or unresolved business question can be material without being a confirmed outcome. Conversely, a clearly observed incidental operation is not automatically material.
First identify the substantive meeting topics from the complete speech and supplied visual material. For each source window, separate meaningful propositions from surrounding operational context; bind each proposition to its actual object, relationship, value/unit, time role, condition, responsibility and status. Preserve a clearly expressed request's timing and constraints even when the responsible person's identity is unknown. Do not replace a recommendation with an observed page or confuse an open question with an established defect.
Treat capture controls, interface chrome, counters, connection checks, casual acknowledgments and unrelated screen state as incidental unless the meeting substantively discusses them as a topic, requirement, demonstration result or constraint. Visibility alone does not establish business relevance. Do not create a business topic merely to inventory incidental UI.
Do not turn isolated numbers, role-less time readings or garbled names into business facts. Retain the coherent supported part of a substantive proposition; keep a material uncertainty briefly attached to the affected business point. If no meaningful proposition can be established, use empty coverage fact_ids with a source-grounded reason instead of manufacturing a fact or a section of transcription caveats. No source window or frame is required to yield a business fact.
Consolidate genuinely repeated propositions only after checking the same object, scope, condition, time role and status; preserve differences as distinct facts. Then classify each unique candidate's material flag separately according to its bearing on the substantive topics. Do not copy the schema example's true value to every fact. A false flag may carry an optional material_reason; the final reviewer must still check the original source rather than trust that flag.'''


SOURCE_SWEEP_RULE = '''\nSUBSTANTIVE SOURCE SWEEP AND RELATION CHECK.
Read each complete speech window and each supplied visual source independently before consolidating topics. For a message, task, document or request card, Read the substantive body before its title, identifier or surrounding controls. Record what is requested or constrained, not merely that someone created, shared or opened an item. Follow the trigger, requested behavior, expected outcome and constraints when the source actually supplies them. A visible requirement or follow-up may be material even if the speech only mentions the workflow; independent screen content does not need a spoken repetition. The body of a discussed request is substantive content, not interface chrome. Keep it separate from adjacent notification, publication or navigation controls unless the source establishes the relationship.
Keep the original force and time role: a request stays a request, a suggestion stays a suggestion, a condition stays attached to its outcome, and a relative deadline is retained without inventing a calendar date or owner. Preserve legible multiplicity, named options, direction, qualification requirements and visible changes of plan when they affect the discussion; editing or crossing out a proposal alone does not establish a final decision.
Check that the base proposition is established before qualifying its details: uncertainty starts at the base event or object, not only at its attributes. Do not convert an unclear phrase into a specific event, material category, device, setting, quantity target or replacement plan and then add a disclaimer about unknown details. Preserve a clear conditional, comparison or quantity relationship without supplying an uncertain noun or domain from context. Do not add causation, substitution, ownership, agreement or completion merely to make fragmented text read smoothly. If no coherent business relation remains, reject the candidate with its source reason instead of listing corrupted words in the report.
After organizing the report, sweep the complete sources again for substantive requests, requirements, alternatives and constraints absent from the working list or only mentioned by an identifier. Check missing relations as well as false claims. Consolidate repeated arrangements without losing their distinct conditions; remove incidental state and noise rather than shortening useful requirements to make room for them.'''


RELATION_FIDELITY_RULE = '''\nPRESERVE RELATIONAL DIMENSIONS THROUGH BOTH PASSES.
Before consolidation, organize each substantive source proposition as trigger -> action -> outcome, with its actual stage, scope, time role and status when supplied. Keep independently stated conditions distinct, even when they share an outcome or destination. A broad statement about a later problem does not cover a specific trigger or a numbered stage. Do not add missing dimensions or force every proposition into this shape.
For a diagram, read each directed edge as source endpoint -> relation -> target endpoint. Preserve each edge and its direction separately before combining prose. Distinct input, output, feedback and control paths cannot be replaced with a shared undirected phrase merely because they meet at one component. Labels or spatial proximity without a readable edge do not establish a connection; do not infer an obscured arrow.
For every reported number, recheck value, unit, object, configuration, source state and time role together against the actual supporting source. Verify the decimal point, digit grouping and sign rather than borrowing a nearby number or plausible value. Different selections or configurations remain separate comparisons. A visible number without a reliable object/value binding is not a useful precise comparison; omit the unsupported precision while retaining supported qualitative information. A disclaimer about purchase or selection status does not validate a number. Source references identify where to check; they do not prove that an obscured value is legible.
Do not discard an independently intelligible deadline, requirement strength, condition or stage merely because an adjacent noun or speaker identity is unclear. Preserve the supported clause with an appropriately limited description and relative time, without supplying a guessed object, named owner or calendar date. Distinguish a deadline or future arrangement from a historical recollection and from an incidental time reading. Reject only the unsupported portion when the remaining substantive relationship is independently clear.
After writing or merging, compare the final sentence against both the original source and the working candidate for these dimensions. Restore a supported condition, stage, deadline, number binding or directed edge lost in paraphrase; if the working candidate was wrong, correct it from the source instead. An included audit passage must retain the material relationship, not just its topic or shared nouns. Perform this comparison internally within the existing draft and whole-source review; return the existing JSON schema, not an extra checklist, call or fixed report section.'''


REVIEW_ACCOUNTING_RULE = '''\nINDEPENDENT REVIEW AND FINAL-BODY ACCOUNTING.
1. Reconstruct the substantive meeting account from the complete original material. Use the working facts as a fallible coverage checklist, not as the authority for relevance, relationships or final structure. Recheck source propositions missing from that checklist too.
2. Independently correct relevance and source validity before deciding output depth. A candidate may be rejected for non_meeting, incidental or garbled source-grounded reasons even when the draft marked material=true. Use disposition rejected with an explicit reason explaining why the original source does not establish a relevant substantive proposition. These are source/relevance corrections, not omitted_for_depth. A missing final decision, uncertain outcome or unknown owner is not by itself grounds to reject a supported proposal, request, question, condition or documented assignment. Never reject supported important matters merely to shorten the report.
3. Write the final report around the actual topics. Preserve supported requirements, time roles, quantities, alternatives, dependencies, rationale and changes of position with their original relationships. Keep uncertainty only where it materially affects understanding; do not inventory unresolvable phrases or add an appendix of incidental capture/interface state.
4. Audit the actual final body after it has been written and consolidated. Merged duplicates are included: give every covered fact an included row pointing to the same final passage where appropriate. This is not omission. The quoted passage must express that fact's actual relationship, status and material qualifiers, not an unrelated neighboring paragraph or a paragraph sharing only a label. A displayed item cannot stand in for a recommendation to seek it; generic topic wording cannot stand in for an explicit requirement. Do not require literal reproduction of every working-fact field; natural paraphrase is allowed if the relationship and constraints remain intact.
Before returning, independently compare the final report with the whole source and restore missing supported important details. In detailed mode a still-valid material fact cannot be omitted_for_depth: restore it, account for it as included in a merged passage, or reject a genuinely mistaken working candidate using a specific original-source reason. Do not relabel a real omission as rejection. This audit is an accountability record, not proof that the returned prose is factually correct.'''


def prepare_fact_material(text, source, *, require_protocol=None):
    value = _json(text)
    if require_protocol is not None:
        _require(value.get('protocol') == require_protocol)
    if value.get('protocol') == 2:
        from app.llm.meeting_fact_protocol import prepare
        return prepare(value)
    _require(value.get('protocol', 1) == 1)
    topics = _ids(value.get('topics'), 'id')
    facts = _ids(value.get('facts'), 'id')
    refs = supplied_refs(source)
    for fact in value['facts']:
        fact.setdefault('material', True)
        fact.setdefault('qualifiers', [])
        _require(fact.get('topic_id') in topics and type(fact.get('material')) is bool)
        _require(all(isinstance(fact.get(key), str) and fact[key].strip()
                     for key in ('subject', 'relation', 'object', 'status')))
        _require(isinstance(fact.get('qualifiers'), list) and all(isinstance(q, str) for q in fact['qualifiers']))
        _require(isinstance(fact.get('source_refs'), list) and fact['source_refs']
                 and all(isinstance(ref, str) and ref in refs for ref in fact['source_refs']))
    _require(_ids(value.get('coverage'), 'source_ref') == refs)
    covered = set()
    for row in value['coverage']:
        ids = row.get('fact_ids')
        _require(isinstance(ids, list) and all(isinstance(key, str) and key in facts for key in ids))
        _require(bool(ids) or isinstance(row.get('reason'), str) and bool(row['reason'].strip()))
        # Coverage is a navigation/checklist association, not a second evidence
        # graph. Do not invent support edges to mirror the two model lists.
        covered.update(ids)
    _require(covered == facts)
    return json.dumps(value, ensure_ascii=False)


def finalize_fact_review(text, draft, source):
    state = presentation_state()
    if state:
        state.raw_review = text
    value, material = _json(text), _json(draft)
    if material.get('protocol') == 2:
        from app.llm.meeting_fact_protocol import finalize
        return finalize(value, material)
    _require(value.get('protocol', 1) == 1)
    markdown = value.get('markdown')
    _require(isinstance(markdown, str) and bool(markdown.strip()))
    proof_body = _proof_quote_text(markdown)
    facts = {fact['id']: fact for fact in material['facts']}
    _require(_ids(value.get('audit'), 'fact_id') == set(facts))
    included = {}
    for row in value['audit']:
        disposition, passage, reason = row.get('disposition'), row.get('passage'), row.get('reason')
        _require(disposition in {'included', 'omitted_for_depth', 'rejected'})
        if disposition == 'included':
            _require(isinstance(passage, str) and passage.strip() and _proof_quote_text(passage) in proof_body)
            included[row['fact_id']] = passage
        else:
            _require(isinstance(reason, str) and reason.strip() and passage == '')
            if disposition == 'omitted_for_depth' and state and state.depth == 'detailed':
                _require(not facts[row['fact_id']]['material'])
    _require(_ids(value.get('topic_audit'), 'topic_id') == {topic['id'] for topic in material['topics']})
    for row in value['topic_audit']:
        passage, reason = row.get('passage'), row.get('reason')
        _require(isinstance(passage, str) and isinstance(reason, str))
        if passage.strip():
            # A reason cannot rescue a quote with changed or missing content.
            _require(_proof_quote_text(passage) in proof_body)
        else:
            _require(passage == '' and bool(reason.strip())
                     and not any(fact['topic_id'] == row['topic_id'] and key in included
                                 for key, fact in facts.items()))
    figures = value.get('figures')
    _require(isinstance(figures, list) and len(figures) <= 8)
    _require(not re.search(r'\[(?:ASR|FRAME):|!\[|\[\[Screenshot:', markdown))
    if state and state.presentation == 'illustrated':
        _require(bool(figures))
        refs = supplied_refs(source)
        selected = set()
        for figure in figures:
            _require(isinstance(figure, dict))
            ref, ids, passage = figure.get('frame_ref'), figure.get('fact_ids'), figure.get('after_passage')
            _require(isinstance(ref, str) and re.fullmatch(r'\[FRAME:\d{4,}\]', ref) and ref in refs and ref not in selected)
            _require(isinstance(ids, list) and ids and all(isinstance(key, str) and key in included and ref in facts[key]['source_refs'] for key in ids))
            _require(isinstance(passage, str) and passage.strip() and markdown.count(passage) == 1
                     and all(passage in included[key] or included[key] in passage for key in ids))
            caption = figure.get('caption')
            _require(isinstance(caption, str) and 0 < len(caption) <= 160 and not re.search(r'[\[\]<>\r\n]', caption))
            selected.add(ref)
        # Insert only after validating every choice, preserving the exact reviewed prose.
        for figure in figures:
            passage = figure['after_passage']
            markdown = markdown.replace(passage, passage + '\n\n' + figure['frame_ref'], 1)
        state.figures[:] = figures
    else:
        _require(not figures)
    return markdown.strip()


DRAFT_PROTOCOL = '''AUTOMATIC FACT MATERIAL PROTOCOL 1. Return one JSON object, no Markdown wrapper:
{"topics":[{"id":"T001","title":"source-grounded topic"}],"facts":[{"id":"F001","topic_id":"T001","subject":"actual object or actor","relation":"precise relation including direction and time role","object":"value with its unit or related object","qualifiers":["conditions, scope, negation, dependencies, uncertainty"],"status":"proposal, comparison, document assignment, commitment or confirmed outcome as supported","source_refs":["[ASR:0001]"],"material":true}],"coverage":[{"source_ref":"[ASR:0001]","fact_ids":["F001"],"reason":""}]}.
Create your own facts from the complete source. These are schema descriptions, never meeting facts. Separate claims until object/configuration/time role/scope match; keep actor, number/unit, condition, direction and state in the same fact. Missing information stays absent, never inferred from convention. Every supplied ASR and FRAME reference must occur exactly once in coverage; a substantive window may support multiple facts, and a fact may cite multiple windows. Non-substantive references use empty fact_ids with a short reason. Every fact must be covered by its actual source references. Preserve substantive comparisons, changed plans, constraints, rationale and relevant independently legible visual facts, not just final decisions. A temporal overlap alone cannot link an image to a spoken fact. Working material does not impose final report headings. Do not compress these facts for the requested output depth yet.'''


REVIEW_PROTOCOL = '''AUTOMATIC FACT REVIEW PROTOCOL 1. The response is one JSON object, no Markdown wrapper:
{"markdown":"final automatic report in the requested language and depth","audit":[{"fact_id":"F001","disposition":"included","passage":"exact substring in markdown containing the checked fact and its relationships","reason":""}],"topic_audit":[{"topic_id":"T001","passage":"exact substring in markdown covering this topic","reason":""}],"figures":[]}.
The markdown field alone is the final report. Keep the audit outside it. Check each fact's subject/relation/object/qualifiers/status together against the complete original source. A shared name/number or nearby sentence does not establish a relationship. Correct relationships in the report; never merely append a disclaimer. Every draft fact must occur exactly once in audit: included requires an exact report passage; rejected requires empty passage and a specific source-grounded reason; omitted_for_depth requires empty passage and a selection reason. Detailed output cannot omit material facts for depth. Rejection is only for unsupported/incorrect claims, never a shortcut for shortening. Consolidated facts may cite the same passage. Audit every topic once with a real passage or a specific reason why no supported fact remains. Re-read all supplied windows and visual sources for omissions beyond the working facts and restore missing supported details directly in markdown. No fixed sections or counts. No internal ASR/FRAME IDs, image URLs or screenshot placeholders in markdown.'''
