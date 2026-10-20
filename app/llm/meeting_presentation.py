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
        'brief': 'Content depth: brief. Select the essential supported outcomes and material conditions for a quick reading. Omit secondary examples and repetition. Brevity may select facts but must never change their relationships, status, uncertainty, owners or deadlines.',
        'concise': 'Content depth: concise. Cover the substantive topics, outcomes, rationale and explicit follow-ups compactly. Remove repetition and secondary examples while preserving material conditions and disagreements.',
        'detailed': 'Content depth: detailed. Preserve substantive source-supported explanations, examples, comparisons, constraints, disagreements and changes of plan without repeating facts.',
    }
    return instructions.get(depth, '') + ('\nChoose headings from the actual content; no fixed sections, counts or action tables. The report field contains Markdown facts only; do not generate HTML, images, image URLs or screenshot placeholders.' if depth else '')


def presentation_availability(*, has_visuals):
    return {
        'text': {'available': True},
        'html': {'available': True},
        'illustrated': {'available': bool(has_visuals), 'reason': None if has_visuals else '缺少已核验的原视频截图，无法生成图文。'},
        'comic': {'available': False, 'reason': '当前未接通所选模型的真实图像生成及结果核验，漫画不可用；不会更换模型。'},
        'infographic': {'available': False, 'reason': '当前未接通可核验的信息图生成链路，信息图不可用。'},
    }
