"""Code-fence-aware, strictly idempotent Markdown injector for VINote visual slides.

Inserts Feishu-compatible standalone image paragraphs:
``![safe_caption](/api/task/{task_id}/artifacts/visuals/{filename})``
leaving user prose, fenced code blocks, and ``/artifacts/screenshots/`` untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

_TASK_ID_RE = re.compile(r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}\Z")
_VISUAL_PNG_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}\.png\Z")
_FENCE_OPEN_RE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})")
_HEADING_RE = re.compile(r"^[ ]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*\r?\n?\Z")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_NORMALIZE_HEADING_RE = re.compile(r"[\s`*_~#：:、，,。.\-—()（）\[\]【】]+")
MAX_CAPTION_LEN = 120


@dataclass(frozen=True)
class SlideInsertion:
    filename: str
    caption: str
    target_heading: str


def _validate_task_id(task_id: str) -> str:
    if not isinstance(task_id, str) or not _TASK_ID_RE.fullmatch(task_id):
        raise ValueError("Invalid canonical task_id")
    return task_id


def _validate_filename(filename: str) -> str:
    if not isinstance(filename, str) or not _VISUAL_PNG_RE.fullmatch(filename):
        raise ValueError("Invalid visual slide filename")
    return filename


def sanitize_caption(caption: str, *, fallback: str = "可视化图解") -> str:
    if not isinstance(caption, str):
        return fallback
    cleaned = _CONTROL_CHARS_RE.sub(" ", caption)
    cleaned = cleaned.replace("[", " ").replace("]", " ")
    cleaned = " ".join(cleaned.split()).strip()
    if not cleaned:
        return fallback
    return cleaned[:MAX_CAPTION_LEN].rstrip()


def _slide_line_pattern(task_id: str) -> re.Pattern[str]:
    escaped_id = re.escape(task_id)
    return re.compile(
        rf"^[ ]{{0,3}}!\[[^\]\r\n]{{0,500}}\]"
        rf"\(/api/task/{escaped_id}/artifacts/visuals/[A-Za-z0-9_-]{{1,120}}\.png\)[ \t]*\r?\n?\Z"
    )


def _iter_fence_states(lines: list[str]) -> list[bool]:
    """Return a list of booleans where True means the line is inside (or delimits) a code fence."""
    in_fence_flags: list[bool] = []
    fence_char: str | None = None
    fence_len = 0

    for line in lines:
        stripped = line.rstrip("\r\n")
        if fence_char is None:
            match = _FENCE_OPEN_RE.match(stripped)
            if match:
                marker = match.group(1)
                # CommonMark: backtick fence info string cannot contain backticks
                rest = stripped[match.end():]
                if marker[0] == "`" and "`" in rest:
                    in_fence_flags.append(False)
                    continue
                fence_char = marker[0]
                fence_len = len(marker)
                in_fence_flags.append(True)
            else:
                in_fence_flags.append(False)
        else:
            in_fence_flags.append(True)
            close_re = re.compile(rf"^[ ]{{0,3}}{re.escape(fence_char)}{{{fence_len},}}[ \t]*\Z")
            if close_re.match(stripped):
                fence_char = None
                fence_len = 0

    return in_fence_flags


def strip_visual_slides(markdown: str, task_id: str) -> str:
    """Remove standalone visual slide paragraphs belonging to ``task_id`` outside code fences."""
    _validate_task_id(task_id)
    if not markdown:
        return markdown

    lines = markdown.splitlines(keepends=True)
    in_fence = _iter_fence_states(lines)
    pattern = _slide_line_pattern(task_id)

    slide_indices = {
        idx for idx, line in enumerate(lines)
        if not in_fence[idx] and pattern.fullmatch(line) is not None
    }
    if not slide_indices:
        return markdown

    skip: set[int] = set(slide_indices)
    for idx in sorted(slide_indices):
        if idx + 1 < len(lines) and idx + 1 not in skip and lines[idx + 1].strip() == "":
            skip.add(idx + 1)
        elif idx - 1 >= 0 and idx - 1 not in skip and lines[idx - 1].strip() == "":
            skip.add(idx - 1)

    return "".join(line for idx, line in enumerate(lines) if idx not in skip)


def _normalize_heading_key(text: str) -> str:
    cleaned = re.sub(r"^\s*#{1,6}\s+", "", text.strip())
    return _NORMALIZE_HEADING_RE.sub("", cleaned).lower()


def _match_heading_index(
    target_heading: str,
    h2_headings: list[tuple[int, str, str]],
    h1_headings: list[tuple[int, str, str]],
) -> int:
    """Return line index to insert after, or -1 for top of document."""
    norm_target = _normalize_heading_key(target_heading or "")
    raw_target = re.sub(r"^\s*#{1,6}\s+", "", (target_heading or "").strip()).strip().lower()

    if norm_target and h2_headings:
        # 1. Exact raw text match
        for idx, raw, _ in h2_headings:
            if raw.lower() == raw_target:
                return idx
        # 2. Exact normalized match
        for idx, _, norm in h2_headings:
            if norm == norm_target:
                return idx
        # 3. Substring match
        for idx, _, norm in h2_headings:
            if norm and (norm_target in norm or norm in norm_target):
                return idx

    # Fallback: first ## heading, else first # heading, else top of document
    if h2_headings:
        return h2_headings[0][0]
    if h1_headings:
        return h1_headings[0][0]
    return -1


def insert_visual_slides(
    markdown: str,
    task_id: str,
    slides: Sequence[SlideInsertion],
) -> str:
    """Idempotently inject visual slide image paragraphs into meeting Markdown."""
    _validate_task_id(task_id)
    validated: list[tuple[str, str, str]] = []
    for slide in slides:
        filename = _validate_filename(slide.filename)
        caption = sanitize_caption(slide.caption, fallback=filename[:-4])
        validated.append((filename, caption, slide.target_heading or ""))

    base = strip_visual_slides(markdown, task_id)
    if not validated:
        return base

    lines = base.splitlines(keepends=True)
    in_fence = _iter_fence_states(lines)
    newline = "\r\n" if "\r\n" in base else "\n"

    h1_headings: list[tuple[int, str, str]] = []
    h2_headings: list[tuple[int, str, str]] = []
    for idx, line in enumerate(lines):
        if in_fence[idx]:
            continue
        match = _HEADING_RE.fullmatch(line)
        if not match:
            continue
        level = len(match.group(1))
        raw_text = match.group(2).strip()
        norm_text = _normalize_heading_key(raw_text)
        if level == 2:
            h2_headings.append((idx, raw_text, norm_text))
        elif level == 1:
            h1_headings.append((idx, raw_text, norm_text))

    grouped: dict[int, list[str]] = {}
    for filename, caption, target_heading in validated:
        anchor = _match_heading_index(target_heading, h2_headings, h1_headings)
        md_line = f"![{caption}](/api/task/{task_id}/artifacts/visuals/{filename}){newline}"
        grouped.setdefault(anchor, []).append(md_line)

    out: list[str] = []
    if -1 in grouped:
        for img_line in grouped[-1]:
            out.append(img_line)
            out.append(newline)

    for idx, line in enumerate(lines):
        if idx not in grouped:
            out.append(line)
            continue

        # Ensure heading line terminates with newline before inserting slide paragraphs
        heading_line = line if line.endswith(("\n", "\r")) else line + newline
        out.append(heading_line)
        has_next = idx + 1 < len(lines)
        next_is_blank = has_next and lines[idx + 1].strip() == ""

        out.append(newline)
        slide_lines = grouped[idx]
        for s_idx, img_line in enumerate(slide_lines):
            out.append(img_line)
            if s_idx < len(slide_lines) - 1:
                out.append(newline)
        if has_next and not next_is_blank:
            out.append(newline)

    return "".join(out)
