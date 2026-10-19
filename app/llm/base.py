"""
LLM abstraction base class.
"""
from abc import ABC, abstractmethod
from typing import Callable, List

from app.models.transcript import TranscriptSegment

SummaryProgressCallback = Callable[[str], None]


class LLMSummarizer(ABC):
    """Base interface for transcript-to-note summarizers."""

    def configure_video_capabilities(self, capabilities: dict | None,
                                     *, image_input_verified: bool = False) -> None:
        """Use metadata/test evidence for this exact instance's selected model.

        image_input_verified may be set only after an explicitly authorized actual
        image+text compatibility check for this model and endpoint. No check or
        catalog request is initiated here; names never imply image support.
        """
        self._video_capabilities = dict(capabilities or {})
        if image_input_verified is True:
            self._video_capabilities['vision'] = True
        self._video_capability_model = getattr(self, 'model', None)

    @abstractmethod
    def summarize(
        self,
        title: str,
        segments: List[TranscriptSegment],
        style: str = "detailed",
        summary_mode: str = "default",
        extras: str | None = None,
        output_language: str = "zh-CN",
        progress_callback: SummaryProgressCallback | None = None,
        video_evidence=None,
    ) -> str:
        """Convert transcript segments into structured Markdown notes."""
        ...
