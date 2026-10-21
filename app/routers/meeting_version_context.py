"""Main thread mounts this factory under /api; no worker startup here."""
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from app.models.source_request import SourceRequestReceipt
from app.services.meeting_version_context import MeetingVersionConfirmation, MeetingVersionService


def create_meeting_version_router(service=None, principal=None, note_service=None, active=None, fresh_service=None):
    if principal is None:
        from app.services.generation_auth_service import get_generation_user
        principal = get_generation_user
    service = service or MeetingVersionService(fresh_service=fresh_service)
    active = active or (lambda task: False)
    router = APIRouter(tags=["meeting-versions"])

    @router.get("/task/{task_id}/meeting-version-context")
    def context(task_id: str, response: Response, user=Depends(principal)):
        response.headers["Cache-Control"] = "private, no-store"
        return service.context(user.user_id, task_id, active=active(task_id))

    @router.get("/task/{task_id}/meeting-version-models")
    def models(task_id: str, response: Response, context_revision: str = Query(pattern=r"^[a-f0-9]{64}$"), user=Depends(principal)):
        response.headers["Cache-Control"] = "private, no-store"
        return service.models(user.user_id, task_id, context_revision, active=active(task_id))

    @router.post("/task/{task_id}/meeting-versions", response_model=SourceRequestReceipt)
    def create(task_id: str, body: MeetingVersionConfirmation, background: BackgroundTasks, response: Response, user=Depends(principal)):
        response.headers["Cache-Control"] = "private, no-store"
        return service.accept(user.user_id, task_id, body, background, note_service, active=active(task_id))

    return router
