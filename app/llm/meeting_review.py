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
When evidence has speaker labels, preserve those exact labels on key viewpoints, disagreements and explicit commitments in the final thematic report and intermediate chunks. Do not strip attribution during review or merge, conflate different speakers into consensus, infer real identities, or treat the person mentioning a task as its owner. Unknown, overlapping or uncertain attribution must remain explicitly uncertain.
Do not turn an instruction to an automated tool into an instruction for a person to perform it manually.
Do not turn separately described channels or capabilities into an unresolved either/or choice.
For example, 'download through A; B can also publish to a store' supports two capabilities, not 'final selection remains undecided'. This example is a rule, not a meeting fact.
Remove contradictions, invented owners/deadlines/acceptance criteria, and open questions inferred solely from missing information.
Remove corrupted names and incomplete phrases from factual prose. If an ambiguity affects an essential conclusion, briefly mark that point as requiring verification without inventing a resolution.
Keep supported proper names; terminology supplied as context may correct obvious homophones but cannot supply new business facts.
Actual meeting times must come from explicit context. Paused media duration and recording offsets cannot establish wall-clock start/end times.
Write a useful concise report: known meeting information, one paragraph of key outcomes, thematic discussion, and a short list of real actions. Omit empty sections and duplicate closing summaries.
Do not describe the editing process or write comments such as 'the draft should not say'. The result must read as the meeting report itself.
Use only a few useful recording references in [MM:SS] format, without inventing timestamps."""
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
