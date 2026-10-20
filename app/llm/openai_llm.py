"""
LLM implementations.
"""
import logging
from datetime import timedelta
from typing import List

import httpx
from openai import OpenAI

from app.config import settings
from app.services.tracing_service import (generation_name, record_model_parameters,
                                          record_usage, traced_generation)
from app.llm.anthropic_compat import post_anthropic_compatible
from app.llm.base import LLMSummarizer, SummaryProgressCallback
from app.llm.meeting_review import build_meeting_review_prompts
from app.llm.meeting_draft import build_meeting_draft_prompts
from app.llm.video_material import bind_video_material, video_user_content, anthropic_user_content
from app.llm.source_references import (bind_source_references, record_working_draft,
                                      segment_reference, without_internal_references)
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
        del metadata
        with generation_name(stage):
            return self._complete(**prompts)

    def _complete(self, *, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError

    def _complete_review(self, *, system_prompt: str, user_prompt: str) -> str:
        return self._complete(system_prompt=system_prompt, user_prompt=user_prompt)

    def _review_meeting_note(self, *, source, draft, extras, output_language,
                             intermediate=False, source_is_reviewed_notes=False):
        review_name = "LLM｜核对会议分段" if intermediate else "LLM｜核对最终会议纪要"
        with generation_name(review_name):
            result = self._complete_review(**build_meeting_review_prompts(
                source=source, draft=draft, extras=extras,
                output_language=output_language, intermediate=intermediate,
                source_is_reviewed_notes=source_is_reviewed_notes,
            ))
        from app.llm.meeting_presentation import presentation_state
        if not intermediate and presentation_state() and presentation_state().depth:
            from app.llm.meeting_fact_material import finalize_fact_review
            result = finalize_fact_review(result or '', draft, source)
        else:
            result = (result or '').strip() if intermediate else without_internal_references(result or '')
        if not result:
            raise RuntimeError("会议纪要事实复核未返回内容，请重试。")
        return result

    @staticmethod
    def _format_time(seconds: float) -> str:
        td = timedelta(seconds=int(seconds))
        total_seconds = int(td.total_seconds())
        minutes = total_seconds // 60
        secs = total_seconds % 60
        return f"{minutes:02d}:{secs:02d}"

    def _build_segment_text(self, segments: List[TranscriptSegment]) -> str:
        rendered = []
        for index, seg in enumerate(segments):
            rendered.append(
                f"{segment_reference(seg, index)} {self._format_time(seg.start)}–{self._format_time(seg.end)} - "
                f"{('[' + (seg.speaker_label or seg.speaker_id) + '] ') if seg.speaker_id else ''}{seg.text}")
            if seg.speaker_evidence:
                rendered.append("独立说话人时间轴（录音偏移，编号非实名）：")
                rendered.extend(f"{turn['start']:.2f}–{turn['end']:.2f} 秒：{turn['speaker_id']}"
                                for turn in seg.speaker_evidence)
            if seg.timestamp_estimated:
                rendered.append("转写仅有分段时间；逐句时间与说话人归属不能确证。上述编号仅表示该时间窗内有人发声，不对应任何具体句子；本段观点和承诺统一用‘有人提出/讨论提到’，不得标为某个 speaker 编号。")
        return "\n".join(rendered)

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
        return len(segment.text) + 80 + sum(len(str(turn)) for turn in segment.speaker_evidence)

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
        prompts = (build_meeting_draft_prompts(
            title=title, source=self._build_segment_text(segments), extras=extras,
            output_language=output_language,
        ) if style == 'meeting' else {
            'system_prompt': build_system_prompt(output_language),
            'user_prompt': self._build_user_prompt(title, segments, style, extras, output_language),
        })
        draft = self._complete_stage(
            stage="LLM｜生成会议纪要" if style == "meeting" else "LLM｜生成笔记",
            **prompts,
        )
        if style != "meeting":
            return draft
        record_working_draft(draft)
        from app.llm.meeting_presentation import presentation_state
        if presentation_state() and presentation_state().depth:
            from app.llm.meeting_fact_material import prepare_fact_material
            draft = prepare_fact_material(draft, self._build_segment_text(segments), require_protocol=2)
        if progress_callback:
            progress_callback("正在核对音视频材料并组织会议纪要…")
        return self._review_meeting_note(
            source=self._build_segment_text(segments), draft=draft,
            extras=extras, output_language=output_language,
        )

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
                    stage=f"LLM｜分块总结 {index}/{total_chunks}",
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
            stage="LLM｜合并分块总结",
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
        video_evidence=None,
    ) -> str:
        if video_evidence is not None and normalize_summary_mode(summary_mode) == 'accurate':
            raise ValueError('视频证据需要完整来源总结，请明确选择 default 或 oneshot')
        capabilities = getattr(self, '_video_capabilities', {})
        if getattr(self, '_video_capability_model', None) != getattr(self, 'model', None):
            capabilities = {}  # Verification never transfers to another model.
        with bind_source_references(segments), bind_video_material(video_evidence, capabilities):
            return self._summarize(title, segments, style, summary_mode, extras,
                                   output_language, progress_callback)

    def _summarize(
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
        # Default and explicit oneshot always submit the complete source.
        # Only explicit legacy accurate requests opt into chunk/merge. Provider
        # context errors propagate; they never authorize splitting or replay.
        if mode == "accurate":
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
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=300.0, max_retries=0)
        logger.info("[LLM] init openai-compatible model=%s base_url=%s", model, base_url)

    @traced_generation
    def _complete(self, *, system_prompt: str, user_prompt: str) -> str:
        record_model_parameters({"temperature": self.temperature})
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": video_user_content(user_prompt)},
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
                "messages": [{"role": "user", "content": anthropic_user_content(user_prompt)}],
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
                    {"role": "user", "content": video_user_content(user_prompt)},
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
