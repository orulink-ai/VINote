"""Ground meeting drafts in source evidence before returning the final note."""

from app.llm.prompts import build_system_prompt, normalize_output_language


def build_meeting_review_prompts(
    *, source: str, draft: str, extras: str | None,
    output_language: str, intermediate: bool = False,
    source_is_reviewed_notes: bool = False,
) -> dict[str, str]:
    language = normalize_output_language(output_language)
    rules = """Review the meeting draft against the supplied evidence and return only the corrected Markdown.
The draft is not evidence. Reconstruct supported conclusions rather than preserving its sentences.
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
Review the complete supplied visual evidence as well as speech. Visible proposals or screen text do not prove spoken agreement, decisions, speaker identity or action ownership. A text-only request supplies extracted visual text only; never claim to have read images that were not supplied. Preserve material cross-source conflicts without inventing a resolution or silently replacing an earlier statement with a later screen value.
Let the actual content determine headings, structure and length; impose no fixed sections, outcome counts, action tables or report template. Preserve useful rationale, examples, constraints, disagreements and changes of position across the whole source. Omit empty sections and duplicate summaries.
Recognition gaps, empty transcript intervals, sampling limitations and processing diagnostics constrain reasoning internally; never turn them into recognition/coverage technical reports, meeting facts or invented open questions. Only a material factual ambiguity may receive a brief contextual verification note.
Do not describe the editing process or write comments such as 'the draft should not say'. The result must read as the meeting report itself.
Keep offsets internal unless the user explicitly requests recording references. In the default report remove repeated time citations and technical evidence commentary. Preserve substantive relationships in diagrams, the rationale for comparisons and supported follow-ups; do not reduce visual evidence to a list of labels."""
    if intermediate:
        rules += (
            "\nThis is an intermediate chunk. Preserve supported actors, decisions, "
            "actions, constraints and evidence timestamps for the final merge. "
            "Do not produce a complete meeting overview from a partial chunk."
        )
    source_label = "Reviewed chunk notes" if source_is_reviewed_notes else "Original transcript"
    return {
        "system_prompt": build_system_prompt(language) + "\n\n" + rules,
        "user_prompt": (
            f"Explicit context and terminology:\n{extras or '(none)'}\n\n"
            f"{source_label}:\n{source}\n\nDraft to check:\n{draft}"
        ),
    }
