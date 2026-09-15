"""
Post-process generated notes with key-moment timestamps and screenshot markers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.transcript import TranscriptSegment
from app.services.video_link_service import build_video_jump_url, format_timestamp_label

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_SCREENSHOT_RE = re.compile(r"\[\[Screenshot:(\d{1,2}):(\d{2})\]\]")
_TIMESTAMP_RE = re.compile(r"(?<!\!)\[(\d{1,2}):(\d{2})(?:-(\d{1,2}):(\d{2}))?\](?!\()")
_LINKED_TIMESTAMP_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:-(\d{1,2}):(\d{2}))?\]\([^)]*\)")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_SUMMARY_TITLE_RE = re.compile(r"\b(summary|takeaways?|wrap ?up|closing)\b", re.IGNORECASE)
_MAX_KEY_MOMENTS = 5


@dataclass(frozen=True)
class _Section:
    heading_index: int
    start_line: int
    end_line: int
    order: int
    level: int
    title: str


class NoteMediaService:
    def enrich_markdown(
        self,
        *,
        markdown: str,
        transcript_segments: list[TranscriptSegment],
        video_url: str,
        output_language: str,
    ) -> str:
        del output_language

        if not markdown.strip():
            return markdown

        lines = markdown.splitlines()
        sections = self._collect_sections(lines)
        if not sections:
            return self._link_plain_timestamps(markdown, video_url)

        key_sections = self._select_key_sections(sections, lines)
        updated_lines = list(lines)
        insertions: list[tuple[int, list[str]]] = []
        section_count = len(sections)
        illustrated_timestamps: set[int] = set()

        for section in sections:
            section_lines = updated_lines[section.start_line : section.end_line]
            cleaned_section_lines = [self._remove_screenshot_markers(line) for line in section_lines]

            if section.heading_index in key_sections:
                seconds = self._select_section_timestamp(
                    section_lines=section_lines,
                    section_order=section.order,
                    section_count=section_count,
                    transcript_segments=transcript_segments,
                )
                if seconds is not None:
                    cleaned_section_lines[0] = self._append_heading_timestamp(
                        heading_line=cleaned_section_lines[0],
                        video_url=video_url,
                        seconds=seconds,
                    )
                    if seconds not in illustrated_timestamps:
                        insertions.append((section.heading_index + 1, self._build_key_moment_block(seconds)))
                        illustrated_timestamps.add(seconds)

            updated_lines[section.start_line : section.end_line] = cleaned_section_lines

        enriched_lines = list(updated_lines)
        for insert_at, block_lines in reversed(insertions):
            enriched_lines[insert_at:insert_at] = block_lines

        enriched = "\n".join(enriched_lines)
        enriched = self._link_plain_timestamps(enriched, video_url)
        enriched = _MULTI_BLANK_RE.sub("\n\n", enriched).strip()
        return enriched

    def _collect_sections(self, lines: list[str]) -> list[_Section]:
        sections: list[_Section] = []
        heading_indexes = [index for index, line in enumerate(lines) if _HEADING_RE.match(line)]

        for order, heading_index in enumerate(heading_indexes):
            match = _HEADING_RE.match(lines[heading_index])
            if not match:
                continue

            next_heading = heading_indexes[order + 1] if order + 1 < len(heading_indexes) else len(lines)
            marker, title = match.groups()
            sections.append(
                _Section(
                    heading_index=heading_index,
                    start_line=heading_index,
                    end_line=next_heading,
                    order=order,
                    level=len(marker),
                    title=title,
                )
            )

        return sections

    def _select_key_sections(self, sections: list[_Section], lines: list[str]) -> set[int]:
        scored_sections: list[tuple[int, int, int]] = []

        for section in sections:
            if section.level <= 1:
                continue

            section_lines = lines[section.start_line : section.end_line]
            body_text = self._normalize_text("\n".join(section_lines[1:]))
            explicit_timestamp = any(
                _TIMESTAMP_RE.search(line) or _LINKED_TIMESTAMP_RE.search(line) or _SCREENSHOT_RE.search(line)
                for line in section_lines
            )
            bullet_count = sum(
                1 for line in section_lines if line.lstrip().startswith(("-", "*", "1.", "2.", "3."))
            )

            score = 0
            if explicit_timestamp:
                score += 5
            if section.level == 2:
                score += 3
            elif section.level == 3:
                score += 2
            if len(body_text) >= 180:
                score += 3
            elif len(body_text) >= 90:
                score += 2
            elif len(body_text) >= 40:
                score += 1
            if bullet_count >= 3:
                score += 1
            if _SUMMARY_TITLE_RE.search(section.title):
                score -= 3

            if score > 0 and (explicit_timestamp or len(body_text) >= 40):
                scored_sections.append((score, 1 if explicit_timestamp else 0, section.order))

        if not scored_sections:
            fallback_sections = [section for section in sections if section.level >= 2]
            return {section.heading_index for section in fallback_sections[: min(3, len(fallback_sections))]}

        scored_sections.sort(key=lambda item: (-item[1], -item[0], item[2]))
        selected_orders = {order for _, _, order in scored_sections[:_MAX_KEY_MOMENTS]}
        return {
            section.heading_index
            for section in sections
            if section.order in selected_orders
        }

    def _select_section_timestamp(
        self,
        *,
        section_lines: list[str],
        section_order: int,
        section_count: int,
        transcript_segments: list[TranscriptSegment],
    ) -> int | None:
        for line in section_lines:
            screenshot_match = _SCREENSHOT_RE.search(line)
            if screenshot_match:
                return int(screenshot_match.group(1)) * 60 + int(screenshot_match.group(2))

            timestamp_match = _TIMESTAMP_RE.search(line)
            if timestamp_match:
                return int(timestamp_match.group(1)) * 60 + int(timestamp_match.group(2))

            linked_timestamp = _LINKED_TIMESTAMP_RE.search(line)
            if linked_timestamp:
                return int(linked_timestamp.group(1)) * 60 + int(linked_timestamp.group(2))

        if not transcript_segments:
            return None

        target_index = round(section_order * (len(transcript_segments) - 1) / max(1, section_count - 1))
        return max(0, int(transcript_segments[target_index].start))

    def _build_key_moment_block(self, seconds: int) -> list[str]:
        label = format_timestamp_label(seconds)
        return [
            "",
            f"[[Screenshot:{label}]]",
            "",
        ]

    def _append_heading_timestamp(self, *, heading_line: str, video_url: str, seconds: int) -> str:
        if _TIMESTAMP_RE.search(heading_line) or _LINKED_TIMESTAMP_RE.search(heading_line):
            return heading_line

        match = _HEADING_RE.match(heading_line)
        if not match:
            return heading_line

        heading_prefix, title = match.groups()
        label = format_timestamp_label(seconds)
        jump_url = build_video_jump_url(video_url, seconds)
        return f"{heading_prefix} {title} [{label}]({jump_url})"

    @staticmethod
    def _remove_screenshot_markers(line: str) -> str:
        return _SCREENSHOT_RE.sub("", line).rstrip()

    def _link_plain_timestamps(self, markdown: str, video_url: str) -> str:
        def replace(match: re.Match[str]) -> str:
            start_minutes = int(match.group(1))
            start_seconds = int(match.group(2))
            total_seconds = start_minutes * 60 + start_seconds
            label = match.group(0)[1:-1]
            return f"[{label}]({build_video_jump_url(video_url, total_seconds)})"

        return _TIMESTAMP_RE.sub(replace, markdown)

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = _SCREENSHOT_RE.sub("", text)
        normalized = _LINKED_TIMESTAMP_RE.sub(lambda match: match.group(0).split("](")[0].lstrip("["), normalized)
        normalized = re.sub(r"[*_`>#-]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()
