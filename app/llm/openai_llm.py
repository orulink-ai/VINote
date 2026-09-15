"""
LLM implementations.
"""
import logging
from datetime import timedelta
from typing import List

import httpx
from openai import OpenAI

from app.config import settings
from app.services.tracing_service import (traced_generation, record_usage, traced,
                                          record_model_parameters, observation)
from app.llm.anthropic_compat import post_anthropic_compatible
from app.llm.base import LLMSummarizer, SummaryProgressCallback
from app.llm.meeting_review import build_meeting_review_prompts
from app.llm.prompts import (
    build_chunk_system_prompt,
    build_chunk_user_prompt,
    build_merge_system_prompt,
    build_merge_user_prompt,
    build_system_prompt,
    build_user_prompt,
    normalize_summary_mode,
)
from app.models.transcript import TranscriptSegment

logger = logging.getLogger(__name__)


class _BasePromptLLM(LLMSummarizer):
    def _complete_stage(self, *, stage, metadata=None, **prompts):
        with observation(stage, as_type="chain", metadata=metadata):
            return self._complete(**prompts)

    def _complete(self, *, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError

    def _complete_review(self, *, system_prompt: str, user_prompt: str) -> str:
        return self._complete(system_prompt=system_prompt, user_prompt=user_prompt)

    def _review_meeting_note(self, *, source, draft, extras, output_language,
                             intermediate=False, source_is_reviewed_notes=False):
        with observation("核对会议纪要事实", as_type="chain"):
            result = self._complete_review(**build_meeting_review_prompts(
                source=source, draft=draft, extras=extras,
                output_language=output_language, intermediate=intermediate,
                source_is_reviewed_notes=source_is_reviewed_notes,
            ))
        if not result or not result.strip():
            raise RuntimeError("会议纪要事实复核未返回内容，请重试。")
        return result.strip()

    @staticmethod
    def _format_time(seconds: float) -> str:
        td = timedelta(seconds=int(seconds))
        total_seconds = int(td.total_seconds())
        minutes = total_seconds // 60
        secs = total_seconds % 60
        return f"{minutes:02d}:{secs:02d}"

    def _build_segment_text(self, segments: List[TranscriptSegment]) -> str:
        return "\n".join(
            f"{self._format_time(seg.start)}–{self._format_time(seg.end)} - "
            f"{('[' + (seg.speaker_label or seg.speaker_id) + '] ') if seg.speaker_id else ''}{seg.text}"
            for seg in segments
        )

    def _build_user_prompt(
        self,
        title: str,
        segments: List[TranscriptSegment],
        style: str,
        extras: str | None,
        output_language: str,
    ) -> str:
        return build_user_prompt(
            title=title,
            segment_text=self._build_segment_text(segments),
            style=style,
            extras=extras,
            output_language=output_language,
        )

    @staticmethod
    def _estimate_segment_size(segment: TranscriptSegment) -> int:
        return len(segment.text) + 16

    def _chunk_segments(self, segments: List[TranscriptSegment]) -> list[list[TranscriptSegment]]:
        if not segments:
            return [segments]

        max_chars = max(2000, int(settings.summary_chunk_max_chars))
        max_segments = max(1, int(settings.summary_chunk_max_segments))
        overlap = max(0, int(settings.summary_chunk_overlap_segments))
        chunks: list[list[TranscriptSegment]] = []
        current: list[TranscriptSegment] = []
        current_chars = 0

        for segment in segments:
            segment_size = self._estimate_segment_size(segment)
            exceeds_limits = current and (
                len(current) >= max_segments or current_chars + segment_size > max_chars
            )
            if exceeds_limits:
                chunks.append(current)
                if overlap > 0:
                    current = current[-overlap:]
                    current_chars = sum(self._estimate_segment_size(item) for item in current)
                else:
                    current = []
                    current_chars = 0

            current.append(segment)
            current_chars += segment_size

        if current:
            chunks.append(current)

        return chunks

    def _should_use_hierarchical_mode(self, segments: List[TranscriptSegment]) -> bool:
        total_chars = sum(self._estimate_segment_size(segment) for segment in segments)
        return (
            len(segments) > max(1, int(settings.summary_default_max_segments))
            or total_chars > max(2000, int(settings.summary_default_max_chars))
        )

    @traced("一次性总结", as_type="chain")
    def _summarize_one_shot(
        self,
        *,
        title: str,
        segments: List[TranscriptSegment],
        style: str,
        extras: str | None,
        output_language: str,
        progress_callback: SummaryProgressCallback | None = None,
    ) -> str:
        user_prompt = self._build_user_prompt(title, segments, style, extras, output_language)
        draft = self._complete(
            system_prompt=build_system_prompt(output_language),
            user_prompt=user_prompt,
        )
        if style != "meeting":
            return draft
        if progress_callback:
            progress_callback("正在对照转写核对会议结论与行动事项…")
        return self._review_meeting_note(
            source=self._build_segment_text(segments), draft=draft,
            extras=extras, output_language=output_language,
        )

    @traced("分块总结与全局合并", as_type="chain")
    def _summarize_hierarchical(
        self,
        *,
        title: str,
        segments: List[TranscriptSegment],
        style: str,
        extras: str | None,
        output_language: str,
        progress_callback: SummaryProgressCallback | None,
    ) -> str:
        chunks = self._chunk_segments(segments)
        if len(chunks) <= 1:
            return self._summarize_one_shot(
                title=title,
                segments=segments,
                style=style,
                extras=extras,
                output_language=output_language,
                progress_callback=progress_callback,
            )

        chunk_notes: list[str] = []
        total_chunks = len(chunks)
        for index, chunk in enumerate(chunks, start=1):
            if progress_callback:
                progress_callback(f"Generating structured chunk notes {index}/{total_chunks}...")

            chunk_notes.append(
                self._complete_stage(
                    stage="总结字幕分块",
                    metadata={"chunk_index": index, "chunk_total": total_chunks},
                    system_prompt=build_chunk_system_prompt(output_language),
                    user_prompt=build_chunk_user_prompt(
                        title=title,
                        segment_text=self._build_segment_text(chunk),
                        chunk_index=index,
                        chunk_total=total_chunks,
                        style=style,
                        extras=extras,
                        output_language=output_language,
                    ),
                )
            )
            if style == "meeting":
                if progress_callback:
                    progress_callback(f"正在核对会议分段 {index}/{total_chunks}…")
                chunk_notes[-1] = self._review_meeting_note(
                    source=self._build_segment_text(chunk), draft=chunk_notes[-1],
                    extras=extras, output_language=output_language, intermediate=True,
                )

        if progress_callback:
            progress_callback("Combining chunk notes into the final note...")

        chunk_notes_text = "\n\n".join(
            f"## Chunk Draft {index}\n{chunk_note.strip()}"
            for index, chunk_note in enumerate(chunk_notes, start=1)
        )
        draft = self._complete_stage(
            stage="合并分块笔记",
            system_prompt=build_merge_system_prompt(output_language),
            user_prompt=build_merge_user_prompt(
                title=title,
                chunk_notes_text=chunk_notes_text,
                style=style,
                extras=extras,
                output_language=output_language,
            ),
        )
        if style != "meeting":
            return draft
        if progress_callback:
            progress_callback("正在核对合并后的会议纪要…")
        return self._review_meeting_note(
            source=chunk_notes_text, draft=draft, extras=extras,
            output_language=output_language, source_is_reviewed_notes=True,
        )

    def summarize(
        self,
        title: str,
        segments: List[TranscriptSegment],
        style: str = "detailed",
        summary_mode: str = "default",
        extras: str | None = None,
        output_language: str = "zh-CN",
        progress_callback: SummaryProgressCallback | None = None,
    ) -> str:
        mode = normalize_summary_mode(summary_mode)
        if mode == "oneshot":
            return self._summarize_one_shot(
                title=title,
                segments=segments,
                style=style,
                extras=extras,
                output_language=output_language,
                progress_callback=progress_callback,
            )

        if mode == "accurate" or self._should_use_hierarchical_mode(segments):
            return self._summarize_hierarchical(
                title=title,
                segments=segments,
                style=style,
                extras=extras,
                output_language=output_language,
                progress_callback=progress_callback,
            )

        return self._summarize_one_shot(
            title=title,
            segments=segments,
            style=style,
            extras=extras,
            output_language=output_language,
            progress_callback=progress_callback,
        )


class OpenAILLM(_BasePromptLLM):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
    ):
        self.model = model
        self.temperature = temperature
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=300.0)
        logger.info("[LLM] init openai-compatible model=%s base_url=%s", model, base_url)

    @traced_generation
    def _complete(self, *, system_prompt: str, user_prompt: str) -> str:
        record_model_parameters({"temperature": self.temperature})
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.temperature,
        )
        record_usage(getattr(response, "usage", None))
        return (response.choices[0].message.content or "").strip()


class AnthropicLLM(_BasePromptLLM):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.minimaxi.com/anthropic",
        model: str = "MiniMax-M2.5",
        temperature: float = 1.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        logger.info("[LLM] init anthropic-compatible model=%s base_url=%s", model, self.base_url)

    def _messages_url(self) -> str:
        if self.base_url.endswith("/v1/messages"):
            return self.base_url
        if self.base_url.endswith("/messages"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/messages"
        return f"{self.base_url}/v1/messages"

    @traced_generation
    def _complete(self, *, system_prompt: str, user_prompt: str) -> str:
        record_model_parameters({"temperature": self.temperature, "max_tokens": 8192})
        response = post_anthropic_compatible(
            url=self._messages_url(),
            api_key=self.api_key,
            json_body={
                "model": self.model,
                "max_tokens": 8192,
                "system": system_prompt,
                "messages": [{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
                "temperature": self.temperature,
            },
            timeout=300.0,
        )
        payload = response.json()
        record_usage(payload.get("usage"))
        for block in payload.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                return (block.get("text") or "").strip()
            block_type = getattr(block, "type", None)
            if block_type == "text":
                return (getattr(block, "text", "") or "").strip()
        return ""


class AzureOpenAILLM(_BasePromptLLM):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.7,
    ):
        self.model = model
        self.temperature = temperature
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        logger.info("[LLM] init azure-openai model=%s base_url=%s", model, self.base_url)

    def _chat_url(self) -> str:
        if "chat/completions" in self.base_url:
            if "api-version=" in self.base_url:
                return self.base_url
            separator = "&" if "?" in self.base_url else "?"
            return f"{self.base_url}{separator}api-version={settings.azure_openai_api_version}"
        return (
            f"{self.base_url}/openai/deployments/{self.model}/chat/completions"
            f"?api-version={settings.azure_openai_api_version}"
        )

    @traced_generation
    def _complete(self, *, system_prompt: str, user_prompt: str) -> str:
        record_model_parameters({"temperature": self.temperature, "max_tokens": 8192})
        response = httpx.post(
            self._chat_url(),
            headers={"Content-Type": "application/json", "api-key": self.api_key},
            json={
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 8192,
                "temperature": self.temperature,
            },
            timeout=300.0,
        )
        response.raise_for_status()
        payload = response.json()
        record_usage(payload.get("usage"))
        return (payload["choices"][0]["message"]["content"] or "").strip()
