"""Orthogonal content depth and presentation; no inference or model selection."""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal
from dataclasses import dataclass, field

ContentDepth = Literal['brief', 'concise', 'detailed']
Presentation = Literal['text', 'illustrated', 'html', 'comic', 'infographic']
_depth = ContextVar('meeting_content_depth', default=None)
_state = ContextVar('meeting_presentation_state', default=None)


@dataclass
class PresentationState:
    depth: str | None
    presentation: str | None
    figures: list = field(default_factory=list)
    raw_review: str | None = None
    visual_review: dict | None = None


def presentation_state():
    return _state.get()


@contextmanager
def presentation_scope(depth: ContentDepth | None, presentation=None):
    token = _depth.set(depth)
    state = PresentationState(depth, presentation)
    state_token = _state.set(state)
    try:
        yield state
    finally:
        _state.reset(state_token)
        _depth.reset(token)


def depth_instructions(depth=None):
    depth = depth or _depth.get()
    instructions = {
        'brief': 'Content depth: brief. Aim for about 30–45 seconds of reading: prioritize the main substantive topics, key arrangements and necessary constraints. Omit secondary comparisons, peripheral wording, examples and repetition rather than itemizing everything. This is a reading goal, not a fixed section count or a hard truncation. Brevity may select facts but must never change their relationships, status, uncertainty, owners or deadlines.',
        'concise': 'Content depth: concise. Cover the substantive topics, outcomes, rationale and explicit follow-ups compactly. Remove repetition and secondary examples while preserving material conditions and disagreements.',
        'detailed': 'Content depth: detailed. Preserve substantive source-supported explanations, examples, comparisons, constraints, disagreements and changes of plan without repeating facts.',
    }
    return instructions.get(depth, '') + ('\nChoose headings from the actual content; no fixed sections, counts or action tables. The report field contains Markdown facts only; do not generate HTML, images, image URLs or screenshot placeholders.' if depth else '')


def final_depth_selection(depth):
    """Resolve publication selection separately from complete source checking."""
    choices = {
        'brief': ('Select a short introduction to the meeting purpose, main substantive results or arrangements, '
                  'and constraints necessary to understand them. Secondary specifications, comparisons, examples '
                  'and supporting detail may remain out of the report even when valid and material. '
                  'Do not turn an introduction into a topic-by-topic source inventory.'),
        'concise': ('Select a compact account of the substantive topics, their important outcomes or open choices, '
                    'rationale and actionable follow-ups. Secondary valid details may remain out of the report; '
                    'keep a necessary condition or disagreement with every selected proposition.'),
        'detailed': ('Include every still-valid material proposition, naturally consolidating duplicates without '
                     'losing distinct relationships or qualifiers. Do not use omitted_for_depth for material=true.'),
    }
    if depth not in choices:
        return ''
    return ('\nFINAL REPORT SELECTION PRIORITY. Complete source checking is not complete source publication. '
            'The requested depth controls which valid propositions enter reader-facing blocks; generic '
            'preserve/restore instructions require accuracy of the selected propositions, not publication of '
            'every checked detail at every depth. ' + choices[depth] +
            (' For brief and concise, use omitted_for_depth with a real selection reason for a valid unselected '
             'claim, including material=true; keep its frozen id, field and material unchanged. Do not falsely '
             'reject or reclassify it to shorten the report.' if depth != 'detailed' else '') +
            ' The complete claim ledger may be longer than the report. Keep its accounting outside the '
            'reader-facing blocks. No truncation, fixed headings or extra model call.')


def presentation_availability(*, has_visuals):
    return {
        'text': {'available': True},
        'html': {'available': True},
        'illustrated': {'available': bool(has_visuals), 'reason': None if has_visuals else '缺少已核验的原视频截图，无法生成图文。'},
        'comic': {'available': bool(has_visuals), 'reason': None if has_visuals else '缺少已核验的原视频截图，画面分镜不可用。'},
        'infographic': {'available': True},
    }
