"""Mount this read-only factory under /api; no generation or automatic repair."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.services.summary_visual_artifact import read_summary_visual
from app.services.task_artifact_service import TaskArtifactService


def create_summary_visual_router(artifacts=None, principal=None, sessions=None):
    if principal is None:
        from app.services.generation_auth_service import get_generation_user
        principal = get_generation_user
    artifacts = artifacts or TaskArtifactService()
    router = APIRouter(tags=['summary-visual'])
    headers = {'Cache-Control': 'private, no-store', 'Vary': 'Cookie, Authorization'}

    @router.get('/task/{task_id}/summary-visual')
    def read(task_id: str, user=Depends(principal)):
        owner = user if isinstance(user, str) else user.user_id
        visual = read_summary_visual(artifacts, owner, task_id, sessions=sessions)
        if visual is None:
            raise HTTPException(404, '此版本尚无可核验图形，正文仍可阅读', headers=headers)
        return JSONResponse(visual, headers=headers)

    return router
