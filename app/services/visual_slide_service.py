"""Visual slides orchestrator: plan -> parallel HTML/SVG -> sanitize -> CDP render -> repair -> persist.

Security & VINote invariants:
- Strictly verifies canonical UUID, ``recording_owner``, ``.task_id``, absence of
  ``recording_deleted``, ``status.json == "success"``, and no symlinks/junctions/hardlinks.
- Writes ``visuals/slide-0N.{png,html}`` and ``visuals/manifest.json`` atomically
  (``O_EXCL`` temp + ``fsync`` + ``os.replace``) before idempotently updating ``note.md``
  and ``result.json``.
- Never mutates ``status.json`` or ``NoteDB``; never leaks raw exception text, file paths,
  or credentials into ``manifest.json`` (enumerated ``error_code`` only).
- Deduplicates concurrent per-task invocations via ``_ACTIVE_VISUAL_TASKS``.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import contextvars
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import stat
import threading
from typing import Any, Callable
import uuid

from app.config import settings
from app.services.task_artifact_service import TaskArtifactService
from app.services.visual_slide_markdown import (
    SlideInsertion,
    insert_visual_slides,
    strip_visual_slides,
)
from app.services.visual_slide_prompt import (
    PlannedSlide,
    SlidePlan,
    SlidePromptParseError,
    build_slide_html_prompts,
    build_slide_plan_prompts,
    build_slide_repair_prompts,
    build_vlm_critic_prompts,
    extract_slide_html,
    parse_slide_plan_response,
    parse_slide_review_response,
)
from app.services.visual_slide_renderer import (
    GeometryAudit,
    RenderedSlide,
    VisualRenderError,
    VisualRendererUnavailableError,
    discover_chrome_binary,
    load_bundled_bold_font_bytes,
    load_bundled_font_bytes,
    render_slide_html,
)
from app.services.visual_slide_sanitizer import (
    SanitizedSlideDoc,
    SlideSanitizationError,
    sanitize_slide_html,
)

logger = logging.getLogger(__name__)

PROTOCOL = "visual-slides/1"
MAX_REPAIR_ATTEMPTS = 1
MAX_TOTAL_PNG_BYTES = 24 * 1024 * 1024
VISUALS_DIRNAME = "visuals"
MANIFEST_FILENAME = "manifest.json"
_MAX_RESULT_BYTES = 8 * 1024 * 1024
_MAX_MANIFEST_BYTES = 256 * 1024

_TASK_UUID_RE = re.compile(r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}\Z")
_SLIDE_ARTIFACT_RE = re.compile(r"^slide-(?:0[1-9]|[1-9][0-9])\.(?:png|html)\Z")

ALLOWED_ERROR_CODES = frozenset({
    "renderer_unavailable",
    "llm_unavailable",
    "llm_plan_failed",
    "render_failed",
    "internal_error",
})

_ACTIVE_VISUAL_TASKS: set[str] = set()
_ACTIVE_VISUAL_TASKS_LOCK = threading.Lock()


class VisualSlideSecurityError(ValueError):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


def is_visual_slides_active(task_id: str) -> bool:
    with _ACTIVE_VISUAL_TASKS_LOCK:
        return task_id in _ACTIVE_VISUAL_TASKS


def current_source_markdown_sha256(folder: Path, task_id: str) -> str | None:
    """Return SHA-256 of task result.json markdown stripped of visual slide refs."""
    try:
        raw_result = _read_regular_file(folder / "result.json", _MAX_RESULT_BYTES)
        payload = json.loads(raw_result.decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("markdown"), str):
            return None
        clean = strip_visual_slides(payload["markdown"], task_id)
        return hashlib.sha256(clean.encode("utf-8")).hexdigest()
    except (VisualSlideSecurityError, ValueError, UnicodeDecodeError):
        return None


def _is_junction(path: Path) -> bool:
    return bool(getattr(path, "is_junction", lambda: False)())


def _read_regular_file(path: Path, limit: int) -> bytes:
    """Read one regular single-link non-symlink file with TOCTOU inode identity verification."""
    try:
        before = path.lstat()
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or _is_junction(path)
            or before.st_size > limit
        ):
            raise VisualSlideSecurityError("unsafe_file", "Target is not a single-link regular file")
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        last = path.lstat()
        ident = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_nlink)
        if (
            len(data) > limit
            or ident(before) != ident(opened)
            or ident(opened) != ident(after)
            or ident(after) != ident(last)
        ):
            raise VisualSlideSecurityError("file_changed", "File identity changed during read")
        return data
    except VisualSlideSecurityError:
        raise
    except OSError:
        raise VisualSlideSecurityError("file_unreadable", "Required task file is unavailable") from None


def _ensure_safe_target(target: Path, allowed_parent: Path) -> None:
    parent = target.parent
    if parent.is_symlink() or _is_junction(parent) or parent.resolve() != allowed_parent.resolve():
        raise VisualSlideSecurityError("unsafe_parent", "Write target parent escapes allowed directory")
    if target.exists() or target.is_symlink():
        try:
            info = target.lstat()
        except OSError:
            raise VisualSlideSecurityError("unsafe_target", "Cannot stat write target") from None
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or _is_junction(target)
        ):
            raise VisualSlideSecurityError("unsafe_target", "Write target must not be a symlink or hardlink")


def _atomic_write_bytes(target: Path, data: bytes, *, allowed_parent: Path) -> None:
    _ensure_safe_target(target, allowed_parent)
    tmp_path = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(tmp_path, flags, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _ensure_safe_target(target, allowed_parent)
        os.replace(tmp_path, target)
        if os.name != "nt":
            dir_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        tmp_path.unlink(missing_ok=True)


def _atomic_write_json(target: Path, payload: dict[str, Any], *, allowed_parent: Path) -> None:
    raw = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    _atomic_write_bytes(target, raw, allowed_parent=allowed_parent)


def _ensure_safe_visuals_dir(task_dir: Path, *, create: bool) -> Path:
    visuals_dir = task_dir / VISUALS_DIRNAME
    if visuals_dir.exists() or visuals_dir.is_symlink():
        try:
            info = visuals_dir.lstat()
        except OSError:
            raise VisualSlideSecurityError("unsafe_visuals_dir", "Cannot inspect visuals directory") from None
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or _is_junction(visuals_dir)
            or visuals_dir.resolve().parent != task_dir.resolve()
        ):
            raise VisualSlideSecurityError("unsafe_visuals_dir", "visuals directory is not a safe directory")
        return visuals_dir
    if create:
        visuals_dir.mkdir(mode=0o700, exist_ok=True)
        return _ensure_safe_visuals_dir(task_dir, create=False)
    return visuals_dir


def validate_owned_completed_task(
    artifacts: TaskArtifactService,
    owner: str,
    task_id: str,
) -> Path:
    """Validate ownership, canonical UUID, regular markers, non-deleted, and status == success."""
    if not isinstance(owner, str) or not owner.strip():
        raise VisualSlideSecurityError("invalid_owner", "Owner identity is required")
    if not isinstance(task_id, str) or not _TASK_UUID_RE.fullmatch(task_id):
        raise VisualSlideSecurityError("invalid_task_id", "Canonical task UUID is required")

    folder = artifacts.find_task_dir(task_id)
    if folder is None:
        raise VisualSlideSecurityError("task_not_found", "Task directory not found")
    root = artifacts.output_dir.resolve()
    if (
        folder.is_symlink()
        or _is_junction(folder)
        or not folder.is_dir()
        or folder.resolve().parent != root
    ):
        raise VisualSlideSecurityError("unsafe_task_dir", "Task directory failed containment check")

    deleted_marker = folder / "recording_deleted"
    if deleted_marker.exists() or deleted_marker.is_symlink():
        raise VisualSlideSecurityError("recording_deleted", "Task recording has been deleted")

    try:
        owner_val = _read_regular_file(folder / "recording_owner", 512).decode("utf-8")
        task_val = _read_regular_file(folder / ".task_id", 100).decode("utf-8").strip()
    except UnicodeError:
        raise VisualSlideSecurityError("marker_corrupt", "Task ownership markers are corrupt") from None

    if owner_val != owner or task_val != task_id:
        raise VisualSlideSecurityError("ownership_mismatch", "Task does not belong to caller")

    try:
        status_payload = json.loads(_read_regular_file(folder / "status.json", 65536).decode("utf-8"))
    except (ValueError, UnicodeError):
        raise VisualSlideSecurityError("status_invalid", "Task status.json is unreadable") from None

    if not isinstance(status_payload, dict) or status_payload.get("status") != "success":
        raise VisualSlideSecurityError("task_not_completed", "Task has not completed successfully")

    if (folder / VISUALS_DIRNAME).exists() or (folder / VISUALS_DIRNAME).is_symlink():
        _ensure_safe_visuals_dir(folder, create=False)

    return folder


def read_visual_slides_manifest(
    artifacts: TaskArtifactService,
    owner: str,
    task_id: str,
) -> dict[str, Any] | None:
    """Read-only, auth-verified manifest lookup. Returns None if missing, invalid, or unowned."""
    try:
        folder = validate_owned_completed_task(artifacts, owner, task_id)
        visuals_dir = folder / VISUALS_DIRNAME
        if not visuals_dir.exists():
            return None
        _ensure_safe_visuals_dir(folder, create=False)
        manifest_path = visuals_dir / MANIFEST_FILENAME
        if not manifest_path.exists() and not manifest_path.is_symlink():
            return None
        raw = _read_regular_file(manifest_path, _MAX_MANIFEST_BYTES)
        data = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(data, dict)
            or data.get("protocol") != PROTOCOL
            or data.get("task_id") != task_id
            or data.get("status") not in {"ready", "empty", "failed", "generating"}
            or not isinstance(data.get("slides"), list)
        ):
            return None
        return data
    except (VisualSlideSecurityError, ValueError, UnicodeError, OSError):
        return None


def _encode_vlm_preview(png_bytes: bytes) -> tuple[str, bytes]:
    """Downscale 3200x1800 PNG to a compact 1600x900 JPEG preview for VLM review."""
    from io import BytesIO
    from PIL import Image

    with Image.open(BytesIO(png_bytes)) as img:
        rgb = img.convert("RGB")
        if rgb.size != (1600, 900):
            rgb = rgb.resize((1600, 900), Image.Resampling.LANCZOS)
        for quality in (82, 68, 55):
            buf = BytesIO()
            rgb.save(buf, format="JPEG", quality=quality, optimize=True)
            data = buf.getvalue()
            if len(data) <= 400 * 1024 or quality == 55:
                return "image/jpeg", data
    return "image/jpeg", data


def _build_default_model_callables(
    folder: Path,
    owner: str,
    *,
    want_vlm: bool,
) -> tuple[Callable[[str, str], str], Callable[[str, str, bytes], str] | None, Any]:
    """Build text LLM and optional capability-gated VLM callables from frozen task snapshot."""
    from contextlib import nullcontext
    from app.services.task_model_source import SNAPSHOT_FILE, validate_source, verify_local_config
    from app.services.vilab_cloud_service import VILabCloudService

    snapshot_path = folder / SNAPSHOT_FILE
    snapshot: dict[str, Any] | None = None
    if snapshot_path.exists() or snapshot_path.is_symlink():
        raw_snap = _read_regular_file(snapshot_path, 32768)
        parsed = json.loads(raw_snap.decode("utf-8"))
        snapshot = validate_source(parsed, owner)

    if snapshot and snapshot.get("mode") == "cloud":
        cloud = VILabCloudService()
        model_name = str(snapshot["llm_model"])

        def _extract_choice_content(resp: dict[str, Any]) -> str:
            choices = resp.get("choices") or []
            if not choices or not isinstance(choices[0], dict):
                raise RuntimeError("Empty chat completion choices")
            msg = choices[0].get("message") or {}
            content = msg.get("content", "")
            if isinstance(content, list):
                parts = [p.get("text", "") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)]
                return "".join(parts)
            return str(content or "")

        def cloud_llm(system: str, user: str) -> str:
            resp = cloud.request(
                owner,
                "POST",
                "/openai/v1/chat/completions",
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.2,
                    "stream": True,
                },
                timeout=180,
            )
            return _extract_choice_content(resp)

        vlm_fn: Callable[[str, str, bytes], str] | None = None
        if want_vlm:
            try:
                from app.services.video_model_capability import verify_image_input

                with cloud.task_snapshot(owner, snapshot=snapshot):
                    catalog = cloud.models(owner)
                    entry = next(
                        (row for row in catalog if row.get("id") == model_name and row.get("modelType") == "llm"),
                        None,
                    )
                    if entry is not None and verify_image_input(owner, model_name, catalog_entry=entry):
                        def cloud_vlm(system: str, user: str, png_bytes: bytes) -> str:
                            mime, preview_bytes = _encode_vlm_preview(png_bytes)
                            b64 = base64.b64encode(preview_bytes).decode("ascii")
                            resp = cloud.request(
                                owner,
                                "POST",
                                "/openai/v1/chat/completions",
                                json={
                                    "model": model_name,
                                    "messages": [
                                        {"role": "system", "content": system},
                                        {
                                            "role": "user",
                                            "content": [
                                                {"type": "text", "text": user},
                                                {
                                                    "type": "image_url",
                                                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                                                },
                                            ],
                                        },
                                    ],
                                    "temperature": 0.1,
                                },
                                timeout=90,
                            )
                            return _extract_choice_content(resp)

                        vlm_fn = cloud_vlm
            except Exception as exc:
                logger.info("Visual slides VLM capability unavailable, degrading gracefully: kind=%s", type(exc).__name__)
                vlm_fn = None

        return cloud_llm, vlm_fn, lambda: cloud.task_snapshot(owner, snapshot=snapshot)

    # Local LLM fallback (honors frozen local snapshot fingerprint if present)
    from app.services.llm_service import LLMService

    llm_service = LLMService()
    ctx_factory = (
        (lambda: VILabCloudService().task_snapshot(owner, snapshot=snapshot))
        if snapshot
        else nullcontext
    )
    with ctx_factory():
        config = llm_service.resolve_config(
            user_id=owner,
            model_profile_id=None,
            model_name=None,
            api_key=None,
            base_url=None,
        )
        if snapshot:
            verify_local_config(owner, "llm", config)
        summarizer = llm_service.build_summarizer(config)

    def local_llm(system: str, user: str) -> str:
        if hasattr(summarizer, "_complete"):
            return str(summarizer._complete(system_prompt=system, user_prompt=user))
        if hasattr(summarizer, "client"):
            resp = summarizer.client.chat.completions.create(
                model=config.model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
            )
            return str((resp.choices[0].message.content if resp.choices else "") or "")
        raise RuntimeError("Local summarizer does not support chat completion")

    return local_llm, None, ctx_factory


def _build_manifest(
    *,
    task_id: str,
    status: str,
    source_markdown_sha256: str,
    slides: list[dict[str, Any]],
    dropped_count: int = 0,
    error_code: str | None = None,
) -> dict[str, Any]:
    safe_error = error_code if error_code in ALLOWED_ERROR_CODES else (None if error_code is None else "internal_error")
    return {
        "protocol": PROTOCOL,
        "task_id": task_id,
        "status": status,
        "error_code": safe_error,
        "generated_at": datetime.now().astimezone().isoformat(),
        "source_markdown_sha256": source_markdown_sha256,
        "slide_count": len(slides),
        "dropped_count": max(0, int(dropped_count)),
        "slides": slides,
    }


def _cleanup_stale_slide_files(visuals_dir: Path, keep_filenames: set[str]) -> None:
    try:
        for child in visuals_dir.iterdir():
            if not _SLIDE_ARTIFACT_RE.fullmatch(child.name):
                continue
            if child.name in keep_filenames:
                continue
            try:
                info = child.lstat()
                if stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_nlink == 1:
                    child.unlink(missing_ok=True)
            except OSError:
                continue
    except OSError:
        return


def _generate_slide_html_with_context(
    plan: SlidePlan,
    clean_markdown: str,
    *,
    title: str,
    output_language: str,
    total_slides: int,
    llm_complete: Callable[[str, str], str],
) -> tuple[SlidePlan, str | None]:
    prompts = build_slide_html_prompts(
        plan,
        clean_markdown,
        title=title,
        output_language=output_language,
        total_slides=total_slides,
    )
    try:
        raw = llm_complete(prompts["system"], prompts["user"])
        return plan, extract_slide_html(raw)
    except Exception as exc:
        logger.warning("Visual slide Stage 2 generation failed for %s: kind=%s", plan.id, type(exc).__name__)
        return plan, None


def _patch_markdown_if_fresh(
    folder: Path,
    task_id: str,
    expected_source_sha: str,
    insertions: list[SlideInsertion],
    *,
    strip_only: bool = False,
) -> None:
    """Atomically patch note.md & result.json only if underlying clean prose has not changed."""
    raw_fresh = _read_regular_file(folder / "result.json", _MAX_RESULT_BYTES)
    fresh_payload = json.loads(raw_fresh.decode("utf-8"))
    if not isinstance(fresh_payload, dict) or not isinstance(fresh_payload.get("markdown"), str):
        return
    fresh_md = fresh_payload["markdown"]
    fresh_clean = strip_visual_slides(fresh_md, task_id)
    fresh_sha = hashlib.sha256(fresh_clean.encode("utf-8")).hexdigest()
    if fresh_sha != expected_source_sha:
        logger.info("Visual slides skipping markdown patch due to concurrent edit: task=%s", task_id)
        return
    if strip_only:
        if fresh_md == fresh_clean:
            return
        updated_markdown = fresh_clean
    else:
        updated_markdown = insert_visual_slides(fresh_md, task_id, insertions)
    updated_result = {**fresh_payload, "markdown": updated_markdown}
    _atomic_write_bytes(folder / "note.md", updated_markdown.encode("utf-8"), allowed_parent=folder)
    _atomic_write_json(folder / "result.json", updated_result, allowed_parent=folder)


def generate_visual_slides_for_task(
    artifacts: TaskArtifactService,
    owner: str,
    task_id: str,
    *,
    force: bool = False,
    apply_to_markdown: bool = True,
    llm_complete: Callable[[str, str], str] | None = None,
    vlm_complete: Callable[[str, str, bytes], str] | None = None,
    renderer: Callable[[SanitizedSlideDoc], RenderedSlide] | None = None,
    max_slides: int | None = None,
    output_language: str = "zh-CN",
    vlm_review_enabled: bool | None = None,
) -> dict[str, Any]:
    """Generate, audit, repair (<=1 retry), and persist visual slides for a completed task."""
    folder = validate_owned_completed_task(artifacts, owner, task_id)

    with _ACTIVE_VISUAL_TASKS_LOCK:
        if task_id in _ACTIVE_VISUAL_TASKS:
            return {
                "protocol": PROTOCOL,
                "task_id": task_id,
                "status": "generating",
                "error_code": None,
                "slide_count": 0,
                "dropped_count": 0,
                "slides": [],
            }
        _ACTIVE_VISUAL_TASKS.add(task_id)

    source_sha = ""
    try:
        raw_result = _read_regular_file(folder / "result.json", _MAX_RESULT_BYTES)
        result_payload = json.loads(raw_result.decode("utf-8"))
        if not isinstance(result_payload, dict) or not isinstance(result_payload.get("markdown"), str):
            raise VisualSlideSecurityError("result_invalid", "Task result.json missing markdown")
        raw_markdown = result_payload["markdown"]
        title = str(result_payload.get("title") or "")
        clean_markdown = strip_visual_slides(raw_markdown, task_id)
        source_sha = hashlib.sha256(clean_markdown.encode("utf-8")).hexdigest()

        if not force:
            existing = read_visual_slides_manifest(artifacts, owner, task_id)
            if existing and existing.get("status") in {"ready", "empty"}:
                if existing.get("source_markdown_sha256") == source_sha:
                    return existing

        resolved_max = max(0, min(3, int(settings.visual_slides_max_count if max_slides is None else max_slides)))
        want_vlm = settings.visual_slides_vlm_review_enabled if vlm_review_enabled is None else bool(vlm_review_enabled)

        # Preflight renderer availability before making LLM calls when using default renderer
        if renderer is None:
            configured_url = (getattr(settings, "visual_renderer_url", "") or "").strip()
            configured_chrome = (getattr(settings, "visual_chrome_path", "") or "").strip() or None
            if not configured_url and discover_chrome_binary(configured_chrome) is None:
                visuals_dir = _ensure_safe_visuals_dir(folder, create=True)
                manifest = _build_manifest(
                    task_id=task_id,
                    status="failed",
                    source_markdown_sha256=source_sha,
                    slides=[],
                    error_code="renderer_unavailable",
                )
                _atomic_write_json(visuals_dir / MANIFEST_FILENAME, manifest, allowed_parent=visuals_dir)
                return manifest

            def default_renderer(doc: SanitizedSlideDoc) -> RenderedSlide:
                return render_slide_html(
                    doc,
                    chrome_path=configured_chrome,
                    renderer_url=configured_url or None,
                )

            render_fn = default_renderer
        else:
            render_fn = renderer

        from contextlib import nullcontext

        if llm_complete is None:
            try:
                llm_fn, default_vlm, snapshot_ctx_factory = _build_default_model_callables(
                    folder, owner, want_vlm=want_vlm
                )
            except Exception as exc:
                logger.warning("Visual slides model initialization failed: kind=%s", type(exc).__name__)
                visuals_dir = _ensure_safe_visuals_dir(folder, create=True)
                manifest = _build_manifest(
                    task_id=task_id,
                    status="failed",
                    source_markdown_sha256=source_sha,
                    slides=[],
                    error_code="llm_unavailable",
                )
                _atomic_write_json(visuals_dir / MANIFEST_FILENAME, manifest, allowed_parent=visuals_dir)
                return manifest
            vlm_fn = vlm_complete if vlm_complete is not None else default_vlm
        else:
            llm_fn = llm_complete
            vlm_fn = vlm_complete if want_vlm else None
            snapshot_ctx_factory = nullcontext

        include_font = load_bundled_font_bytes() is not None
        include_bold = include_font and (load_bundled_bold_font_bytes() is not None)

        with snapshot_ctx_factory():
            # Stage 1: Lightweight strict JSON slide planning
            plan_prompts = build_slide_plan_prompts(
                clean_markdown,
                title=title,
                output_language=output_language,
                max_slides=resolved_max,
            )
            try:
                raw_plan = llm_fn(plan_prompts["system"], plan_prompts["user"])
                plans = parse_slide_plan_response(raw_plan, max_slides=resolved_max)
            except (SlidePromptParseError, Exception) as exc:
                logger.warning("Visual slides Stage 1 plan failed: kind=%s", type(exc).__name__)
                visuals_dir = _ensure_safe_visuals_dir(folder, create=True)
                manifest = _build_manifest(
                    task_id=task_id,
                    status="failed",
                    source_markdown_sha256=source_sha,
                    slides=[],
                    error_code="llm_plan_failed",
                )
                _atomic_write_json(visuals_dir / MANIFEST_FILENAME, manifest, allowed_parent=visuals_dir)
                return manifest

            if not plans:
                validate_owned_completed_task(artifacts, owner, task_id)
                visuals_dir = _ensure_safe_visuals_dir(folder, create=True)
                manifest = _build_manifest(
                    task_id=task_id,
                    status="empty",
                    source_markdown_sha256=source_sha,
                    slides=[],
                    dropped_count=0,
                )
                _atomic_write_json(visuals_dir / MANIFEST_FILENAME, manifest, allowed_parent=visuals_dir)
                _cleanup_stale_slide_files(visuals_dir, set())
                if apply_to_markdown and raw_markdown != clean_markdown:
                    _patch_markdown_if_fresh(folder, task_id, source_sha, [], strip_only=True)
                return manifest

            # Stage 2: Parallel bespoke HTML/SVG generation per slide
            generated_html: dict[str, str | None] = {}
            if len(plans) == 1:
                p, html_str = _generate_slide_html_with_context(
                    plans[0],
                    clean_markdown,
                    title=title,
                    output_language=output_language,
                    total_slides=1,
                    llm_complete=llm_fn,
                )
                generated_html[p.id] = html_str
            else:
                with ThreadPoolExecutor(max_workers=min(3, len(plans)), thread_name_prefix="visual-slide") as pool:
                    futures = []
                    for plan in plans:
                        ctx = contextvars.copy_context()
                        futures.append(
                            pool.submit(
                                ctx.run,
                                _generate_slide_html_with_context,
                                plan,
                                clean_markdown,
                                title=title,
                                output_language=output_language,
                                total_slides=len(plans),
                                llm_complete=llm_fn,
                            )
                        )
                    for fut in futures:
                        p, html_str = fut.result()
                        generated_html[p.id] = html_str

            # Stage 3 & 4: Sanitize -> Render + Geometry Audit -> Optional VLM Critic -> Max 1 Repair
            accepted: list[tuple[SlidePlan, SanitizedSlideDoc, RenderedSlide, int, bool]] = []
            cumulative_png_bytes = 0

            for plan in plans:
                current_html = generated_html.get(plan.id)
                if not current_html:
                    continue

                attempts = 0
                while True:
                    sanitized: SanitizedSlideDoc | None = None
                    rendered: RenderedSlide | None = None
                    geom_audit: GeometryAudit
                    vlm_issues: tuple[str, ...] = ()
                    vlm_reviewed = False
                    vlm_passed = True

                    try:
                        sanitized = sanitize_slide_html(
                            current_html,
                            title=plan.title,
                            include_bundled_font=include_font,
                            include_bold_font=include_bold,
                        )
                    except SlideSanitizationError as exc:
                        geom_audit = GeometryAudit(
                            passed=False,
                            issues=(f"sanitization_failed:{exc.code}",),
                            metrics={},
                        )
                    else:
                        try:
                            rendered = render_fn(sanitized)
                            geom_audit = rendered.geometry
                        except VisualRendererUnavailableError:
                            visuals_dir = _ensure_safe_visuals_dir(folder, create=True)
                            manifest = _build_manifest(
                                task_id=task_id,
                                status="failed",
                                source_markdown_sha256=source_sha,
                                slides=[],
                                error_code="renderer_unavailable",
                            )
                            _atomic_write_json(visuals_dir / MANIFEST_FILENAME, manifest, allowed_parent=visuals_dir)
                            return manifest
                        except VisualRenderError as exc:
                            geom_audit = GeometryAudit(
                                passed=False,
                                issues=(f"render_failed:{exc.code}",),
                                metrics={},
                            )

                    slide_obj = PlannedSlide(
                        index=plan.index,
                        id=plan.id,
                        title=plan.title,
                        caption=plan.caption,
                        target_heading=plan.target_heading,
                        visual_rationale=plan.visual_rationale,
                        visual_brief=plan.visual_brief,
                        key_facts=plan.key_facts,
                        html=current_html,
                    )

                    vlm_repaired_html: str | None = None
                    # Skip VLM review if geometry already failed on the final attempt (slide will be dropped).
                    should_run_vlm = (
                        rendered is not None
                        and vlm_fn is not None
                        and (geom_audit.passed or attempts < MAX_REPAIR_ATTEMPTS)
                    )
                    if should_run_vlm:
                        try:
                            vlm_prompts = build_vlm_critic_prompts(
                                slide_obj,
                                geom_audit,
                                markdown_excerpt=clean_markdown[:4000],
                            )
                            raw_review = vlm_fn(vlm_prompts["system"], vlm_prompts["user"], rendered.png_bytes)
                            outcome = parse_slide_review_response(raw_review)
                            vlm_reviewed = True
                            vlm_passed = outcome.passed
                            vlm_issues = outcome.issues
                            vlm_repaired_html = outcome.repaired_html
                        except Exception as exc:
                            logger.warning(
                                "Visual slide VLM critic degraded for %s: kind=%s",
                                plan.id,
                                type(exc).__name__,
                            )
                            vlm_reviewed = False
                            vlm_passed = True
                            vlm_issues = ()

                    if sanitized is not None and rendered is not None and geom_audit.passed and vlm_passed:
                        if cumulative_png_bytes + len(rendered.png_bytes) <= MAX_TOTAL_PNG_BYTES:
                            accepted.append((plan, sanitized, rendered, attempts, vlm_reviewed))
                            cumulative_png_bytes += len(rendered.png_bytes)
                        break

                    if attempts >= MAX_REPAIR_ATTEMPTS:
                        break

                    # Bounded single repair attempt
                    attempts += 1
                    if vlm_repaired_html:
                        current_html = vlm_repaired_html
                        continue
                    repair_prompts = build_slide_repair_prompts(
                        slide_obj,
                        geom_audit,
                        markdown=clean_markdown,
                        vlm_issues=vlm_issues,
                    )
                    try:
                        raw_repaired = llm_fn(repair_prompts["system"], repair_prompts["user"])
                        current_html = extract_slide_html(raw_repaired)
                    except Exception as exc:
                        logger.warning(
                            "Visual slide Stage 4 repair failed for %s: kind=%s",
                            plan.id,
                            type(exc).__name__,
                        )
                        break

        # Re-verify task ownership, .task_id, and non-deleted right before committing artifacts
        validate_owned_completed_task(artifacts, owner, task_id)
        visuals_dir = _ensure_safe_visuals_dir(folder, create=True)

        if not accepted:
            manifest = _build_manifest(
                task_id=task_id,
                status="empty",
                source_markdown_sha256=source_sha,
                slides=[],
                dropped_count=len(plans),
            )
            _atomic_write_json(visuals_dir / MANIFEST_FILENAME, manifest, allowed_parent=visuals_dir)
            _cleanup_stale_slide_files(visuals_dir, set())
            if apply_to_markdown and raw_markdown != clean_markdown:
                _patch_markdown_if_fresh(folder, task_id, source_sha, [], strip_only=True)
            return manifest

        # Commit ordering: slide PNG/HTML files -> manifest.json -> note.md & result.json
        manifest_slides: list[dict[str, Any]] = []
        insertions: list[SlideInsertion] = []
        written_files: set[str] = set()

        for plan, sanitized, rendered, attempts, vlm_reviewed in accepted:
            png_name = f"{plan.id}.png"
            html_name = f"{plan.id}.html"
            _atomic_write_bytes(visuals_dir / png_name, rendered.png_bytes, allowed_parent=visuals_dir)
            _atomic_write_bytes(
                visuals_dir / html_name,
                sanitized.disk_html.encode("utf-8"),
                allowed_parent=visuals_dir,
            )
            written_files.add(png_name)
            written_files.add(html_name)
            manifest_slides.append({
                "index": plan.index,
                "id": plan.id,
                "title": plan.title,
                "caption": plan.caption,
                "target_heading": plan.target_heading,
                "visual_rationale": plan.visual_rationale,
                "png_filename": png_name,
                "html_filename": html_name,
                "image_url": f"/api/task/{task_id}/artifacts/visuals/{png_name}",
                "width": rendered.width,
                "height": rendered.height,
                "png_bytes": len(rendered.png_bytes),
                "png_sha256": rendered.png_sha256,
                "html_sha256": sanitized.html_sha256,
                "renderer_kind": rendered.renderer_kind,
                "repair_attempts": attempts,
                "vlm_reviewed": vlm_reviewed,
                "geometry_passed": True,
            })
            insertions.append(
                SlideInsertion(
                    filename=png_name,
                    caption=plan.caption,
                    target_heading=plan.target_heading,
                )
            )

        manifest = _build_manifest(
            task_id=task_id,
            status="ready",
            source_markdown_sha256=source_sha,
            slides=manifest_slides,
            dropped_count=len(plans) - len(accepted),
        )
        _atomic_write_json(visuals_dir / MANIFEST_FILENAME, manifest, allowed_parent=visuals_dir)
        _cleanup_stale_slide_files(visuals_dir, written_files)

        if apply_to_markdown:
            _patch_markdown_if_fresh(folder, task_id, source_sha, insertions, strip_only=False)

        return manifest
    except VisualSlideSecurityError:
        raise
    except Exception as exc:
        logger.warning(
            "Visual slides generation failed unexpectedly for task=%s: kind=%s",
            task_id,
            type(exc).__name__,
        )
        validate_owned_completed_task(artifacts, owner, task_id)
        visuals_dir = _ensure_safe_visuals_dir(folder, create=True)
        manifest = _build_manifest(
            task_id=task_id,
            status="failed",
            source_markdown_sha256=source_sha,
            slides=[],
            error_code="internal_error",
        )
        _atomic_write_json(visuals_dir / MANIFEST_FILENAME, manifest, allowed_parent=visuals_dir)
        return manifest
    finally:
        with _ACTIVE_VISUAL_TASKS_LOCK:
            _ACTIVE_VISUAL_TASKS.discard(task_id)
