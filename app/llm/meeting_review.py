"""Ground meeting drafts in source evidence before returning the final note."""

from app.llm.prompts import normalize_output_language
from app.llm.meeting_prompt_contract import meeting_system_base
from app.llm.source_references import source_prompt


def build_meeting_review_prompts(
    *, source: str, draft: str, extras: str | None,
    output_language: str, intermediate: bool = False,
    source_is_reviewed_notes: bool = False,
) -> dict[str, str]:
    language = normalize_output_language(output_language)
    from app.llm.meeting_presentation import presentation_state
    state = presentation_state()
    structured = bool(not intermediate and state and state.depth)
    rules = """Review the meeting draft against the supplied evidence and return only the corrected Markdown.
The draft may be source-preservation working notes rather than polished prose. Use them to check coverage, not as the final structure or independent evidence. Synthesize the final meeting report from the full original material, retaining supported concrete details and relationships; do not output a working-note ledger or repeat field labels mechanically.
The draft is not evidence: independently check the full original material. Preserve important source-supported facts and their relationships; correct errors locally and restore omissions from the source. Do not delete or generalize away supported information, or alter its relationships, merely to polish the prose. Remove or correct unsupported claims and relationships without discarding the supported facts around them.
Internal ASR/FRAME references are addresses, not proof. Check each referenced source independently, including the actual image. For each material claim preserve its object, actor or explicitly documented assignee, value and unit, time role, direction, condition and state together. A compatible number or a nearby sentence cannot fill a missing relationship. Recheck that the cited material supports the entire claim rather than one shared keyword; remove or correct a wrong relationship, not merely append a disclaimer. Read the rest of the source too: a draft's citations do not limit coverage. Return only the report, without the internal ASR/FRAME references or an evidence ledger.
Check actors, objects, negations, scope, conditions, and proposals versus confirmed decisions.
ASR text and independent speaker intervals are separate evidence streams on recording offsets. Chunk/file timestamps do not establish word timing or sentence attribution. Never assign all chunk text to one speaker or infer a task owner from interval overlap alone.
Only speaker labels explicitly attached to precisely timed ASR sentences establish attribution. Independent speaker intervals beside chunk/file text do not establish attribution: remove numbered speakers from those viewpoints and commitments and use anonymous wording. This restriction takes precedence over preserving labels from a draft or reviewed chunk notes. For directly attributed sentences preserve those exact labels; never conflate different speakers into consensus, infer real identities, or treat the person mentioning a task as its owner. Unknown, overlapping or uncertain attribution must remain explicitly uncertain.
Do not turn an instruction to an automated tool into an instruction for a person to perform it manually.
Do not turn separately described channels or capabilities into an unresolved either/or choice.
For example, 'download through A; B can also publish to a store' supports two capabilities, not 'final selection remains undecided'. This example is a rule, not a meeting fact.
Remove contradictions, invented owners/deadlines/acceptance criteria, and open questions inferred solely from missing information.
Remove corrupted names and incomplete phrases from factual prose. If an ambiguity affects an essential conclusion, briefly mark that point as requiring verification without inventing a resolution.
Treat corrupted ASR as uncertain source text, never as an established remedy, technical term or decision. Use independently legible material in the same context to resolve a term; do not guess illegible screen words, materials, model names, quantities or prices from plausible lists. Remove unsupported reconstruction from the draft instead of laundering it through review. Preserve clear conditions and arrangements even when nearby fragments are corrupted.
Keep supported proper names; terminology supplied as context may correct obvious homophones but cannot supply new business facts.
Actual meeting times must come from explicit context. Paused media duration and recording offsets cannot establish wall-clock start/end times.
Review the complete supplied visual evidence as well as speech. Independently legible, relevant document plans, assignments, quantities, conditions, due dates and unchecked tasks are usable facts about that document, even when speech does not repeat them. Preserve those details with their actual status; never promote a displayed proposal to spoken agreement, a document assignee to the identity of a speaker, or an unchecked task to completed work. A text-only request supplies extracted visual text only; never claim to have read images that were not supplied. Preserve material cross-source conflicts without inventing a resolution or silently replacing an earlier statement with a later screen value.
Check omissions as well as false claims. Silently compare every major topic in the full speech and visual material against the draft, restoring supported alternatives, comparisons, changing plans, quantities, explicit responsibilities, dependencies and follow-up conditions that matter to the reader. Do not discard a substantive discussion simply because no final decision was made. Do not replace clearly recorded assignments or requirements with a vague statement that a document contains arrangements.
Resolve references across the whole context before counting distinct events or objects. Different attributes or stages of the same event are not separate events unless the evidence distinguishes them. Keep alternatives, estimates and confirmed arrangements separate; preserve ambiguity without inventing an extra event.
Let the actual content determine headings, structure and length; impose no fixed sections, outcome counts, action tables or report template. Preserve useful rationale, examples, constraints, disagreements and changes of position across the whole source. Omit empty sections and duplicate summaries.
Recognition gaps, empty transcript intervals, sampling limitations and processing diagnostics constrain reasoning internally; never turn them into recognition/coverage technical reports, meeting facts or invented open questions. Only a material factual ambiguity may receive a brief contextual verification note.
Do not describe the editing process or write comments such as 'the draft should not say'. Avoid repetitive 'the transcript did not confirm' disclaimers: state the supported plan or material requirement directly, preserving only a substantive uncertainty in its own context. The result must read as the meeting report itself, not a review of the recognition or summarization process.
Keep offsets internal unless the user explicitly requests recording references. In the default report remove repeated time citations and technical evidence commentary. Preserve substantive relationships in diagrams, the rationale for comparisons and supported follow-ups; do not reduce visual evidence to a list of labels."""
    if intermediate:
        rules += (
            "\nThis is an intermediate chunk. Preserve supported actors, decisions, "
            "actions, constraints and evidence timestamps for the final merge. "
            "Do not produce a complete meeting overview from a partial chunk."
        )
    if not intermediate:
        from app.llm.meeting_presentation import depth_instructions
        rules += '\n' + depth_instructions()
        if state and state.depth:
            graphic_protocol = 7 if state.presentation in {'comic', 'infographic'} else 4
            state.expected_review_protocol = graphic_protocol
            from app.llm.meeting_fact_material import REVIEW_MATERIALITY_RULE, SOURCE_SWEEP_RULE, RELATION_FIDELITY_RULE
            from app.llm.meeting_final_review import review_protocol
            rules = rules.replace('return only the corrected Markdown.', 'return protocol-4 report blocks and the final claim ledger.')
            rules = rules.replace('The report field contains Markdown facts only;', 'Report blocks[].markdown contain Markdown facts only;')
            rules = rules.replace('do not output a working-note ledger or repeat field labels mechanically.',
                                  'keep reader-facing blocks free of working-note ledgers or mechanical field labels.')
            rules = rules.replace(
                'Return only the report, without the internal ASR/FRAME references or an evidence ledger.',
                'Keep the reader-facing blocks free of internal ASR/FRAME references and evidence ledgers; '
                'return the machine-readable final claim ledger required below outside those blocks.')
            if graphic_protocol == 7:
                rules = rules.replace('protocol-4 report blocks', 'protocol-7 report parts')
                rules = rules.replace('Report blocks[].markdown contain Markdown facts only;',
                                      'Report blocks[].parts[] strings contain plain text facts only;')
                rules = rules.replace('Let the actual content determine headings, structure and length;',
                                      'Let the actual content determine paragraph grouping, structure and length;')
            rules += '\n\n' + REVIEW_MATERIALITY_RULE + SOURCE_SWEEP_RULE + RELATION_FIDELITY_RULE + review_protocol(state.presentation, protocol=graphic_protocol)
            from app.llm.meeting_presentation import final_depth_selection
            rules += '\n' + final_depth_selection(state.depth)
            from app.llm.meeting_visual_review import visual_review_instructions
            rules += visual_review_instructions(state.presentation, protocol=graphic_protocol)
            if state.presentation == 'illustrated':
                rules += ('\nIllustrated output: choose 1–8 genuinely relevant actual supplied frames during this review. '
                    'Use figures entries {"frame_ref":"[FRAME:0001]","claim_ids":["C1"],'
                    '"after_block_id":"B1",'
                    '"caption":"brief supported description of the actual frame"}. '
                    'Each selected frame must be in the cited included claim evidence and independently support its object/relationship; '
                    'Use each after_block_id only once. Every listed claim_id must include that exact block in '
                    'its block_ids and that exact frame_ref in its own evidence; a neighboring block or frame '
                    'does not qualify. Choose fewer well-bound figures rather than filling a quota or attaching '
                    'unmatched claims to a figure. '
                    'timing proximity alone is insufficient. Return no arbitrary URL. No valid relevant frame means illustrated is incomplete, '
                    'never select opening frames or decorative screenshots just to fill a quota.')
    source_label = "Reviewed chunk notes" if source_is_reviewed_notes else "Original transcript"
    user_prompt = (
        f"Explicit context and terminology:\n{extras or '(none)'}\n\n"
        f"{source_label}:\n{source}\n\nDraft to check:\n{draft}"
    )
    if structured:
        # The working interpretation must not replace the original as the last
        # source text the reviewer sees. Keep both complete, without another call.
        user_prompt = source_prompt(
            f"Fallible working draft to audit (not evidence):\n{draft}\n\n"
            f"Explicit context and terminology:\n{extras or '(none)'}\n\n"
            f"{source_label}:\n", source,
            "\n\nUse the original material to correct the working interpretation, then select the report "
            "at the requested depth. Account for every frozen original claim outside the report blocks."
        )
    return {
        "system_prompt": meeting_system_base(language, structured=structured) + "\n\n" + rules,
        "user_prompt": user_prompt,
    }
