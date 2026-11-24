"""Thin authenticated router for VINote HTML visual slides (GET read-only, POST async queue)."""
from __future__ import annotations

import logging
import threading
from typing import Callable

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.services.task_artifact_service import TaskArtifactService
from app.services.visual_slide_service import (
    PROTOCOL,
    VisualSlideSecurityError,
    current_source_markdown_sha256,
    generate_visual_slides_for_task,
    is_visual_slides_active,
    read_visual_slides_manifest,
    validate_owned_completed_task,
)

logger = logging.getLogger(__name__)


class VisualSlidesGenerateBody(BaseModel):
    force: bool = False


def create_visual_slides_router(
    artifacts: TaskArtifactService | None = None,
    principal=None,
    runner: Callable[..., object] | None = None,
) -> APIRouter:
    if principal is None:
        from app.services.generation_auth_service import get_generation_user
        principal = get_generation_user
    resolved_artifacts = artifacts or TaskArtifactService()
    execute_job = runner or generate_visual_slides_for_task
    queued_tasks: set[str] = set()
    queued_lock = threading.Lock()

    router = APIRouter(tags=["visual-slides"])
    headers = {"Cache-Control": "private, no-store", "Vary": "Cookie, Authorization"}

    def _owner_of(user) -> str:
        return user if isinstance(user, str) else user.user_id

    def _run_background(owner: str, task_id: str, force: bool) -> None:
        try:
            execute_job(resolved_artifacts, owner, task_id, force=force)
        except Exception as exc:
            logger.warning(
                "[VisualSlides] background job failed for task=%s: kind=%s",
                task_id,
                type(exc).__name__,
            )
        finally:
            with queued_lock:
                queued_tasks.discard(task_id)

    @router.get("/task/{task_id}/visual-slides")
    def read_visual_slides(task_id: str, user=Depends(principal)):
        owner = _owner_of(user)
        try:
            validate_owned_completed_task(resolved_artifacts, owner, task_id)
        except VisualSlideSecurityError:
            raise HTTPException(404, "任务不存在或无权访问", headers=headers) from None

        with queued_lock:
            is_queued = task_id in queued_tasks
        if is_queued or is_visual_slides_active(task_id):
            return JSONResponse(
                {
                    "protocol": PROTOCOL,
                    "task_id": task_id,
                    "status": "generating",
                    "error_code": None,
                    "slide_count": 0,
                    "dropped_count": 0,
                    "slides": [],
                },
                headers=headers,
            )

        manifest = read_visual_slides_manifest(resolved_artifacts, owner, task_id)
        if manifest is not None:
            return JSONResponse(manifest, headers=headers)

        return JSONResponse(
            {
                "protocol": PROTOCOL,
                "task_id": task_id,
                "status": "idle",
                "error_code": None,
                "slide_count": 0,
                "dropped_count": 0,
                "slides": [],
            },
            headers=headers,
        )

    @router.post("/task/{task_id}/visual-slides")
    def trigger_visual_slides(
        task_id: str,
        background_tasks: BackgroundTasks,
        body: VisualSlidesGenerateBody | None = Body(default=None),
        user=Depends(principal),
    ):
        owner = _owner_of(user)
        if not settings.visual_slides_enabled:
            raise HTTPException(409, "视觉幻灯片功能已禁用", headers=headers)
        try:
            folder = validate_owned_completed_task(resolved_artifacts, owner, task_id)
        except VisualSlideSecurityError as exc:
            if exc.code == "task_not_completed":
                raise HTTPException(409, "任务尚未完成，暂不能生成视觉幻灯片", headers=headers) from None
            raise HTTPException(404, "任务不存在或无权访问", headers=headers) from None

        force = bool(body.force) if body is not None else False
        if not force:
            existing = read_visual_slides_manifest(resolved_artifacts, owner, task_id)
            if existing is not None and existing.get("status") in {"ready", "empty"}:
                source_sha = current_source_markdown_sha256(folder, task_id)
                if source_sha is not None and existing.get("source_markdown_sha256") == source_sha:
                    return JSONResponse(existing, status_code=200, headers=headers)

        with queued_lock:
            if task_id in queued_tasks or is_visual_slides_active(task_id):
                return JSONResponse(
                    {
                        "protocol": PROTOCOL,
                        "task_id": task_id,
                        "status": "generating",
                        "error_code": None,
                        "slide_count": 0,
                        "dropped_count": 0,
                        "slides": [],
                    },
                    status_code=202,
                    headers=headers,
                )
            queued_tasks.add(task_id)

        background_tasks.add_task(_run_background, owner, task_id, force)
        return JSONResponse(
            {
                "protocol": PROTOCOL,
                "task_id": task_id,
                "status": "queued",
                "error_code": None,
                "slide_count": 0,
                "dropped_count": 0,
                "slides": [],
            },
            status_code=202,
            headers=headers,
        )

    return router
