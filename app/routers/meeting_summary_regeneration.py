"""Desktop router factory; main integration mounts it under /api.

    app.include_router(create_summary_regeneration_router(
        note_service=note._note_service,
        active=lambda task: task in note._ACTIVE_FILE_TASKS), prefix='/api')

GET exposes source.version, transcript_version and context_revision without
catalog/provider access. POST requires {operation_id: UUID, confirmed: true,
context_revision, source_version, model_name: explicit available catalog ID}.
Recover via existing GET /api/source-requests/{operation_id} and /api/task/{id};
neither reserved nor accepted receipts permit another dispatch.

Integration prerequisite in NoteService._transcribe_audio: handle the preloaded
transcript before require_task_execution (which must still guard all ASR).
"""
from fastapi import APIRouter, BackgroundTasks, Depends, Response

from app.models.source_request import SourceRequestReceipt
from app.services.meeting_summary_regeneration import SummaryConfirmation, SummaryRegenerationService


def create_summary_regeneration_router(service=None, principal=None, note_service=None, active=None):
    if principal is None:
        from app.services.generation_auth_service import get_generation_user
        principal = get_generation_user
    service = service or SummaryRegenerationService()
    active = active or (lambda task: False)
    router = APIRouter(tags=['notes'])

    @router.get('/task/{task_id}/summary-context')
    def context(task_id: str, response: Response, user=Depends(principal)):
        response.headers['Cache-Control'] = 'private, no-store'
        return service.context(user.user_id, task_id, active=active(task_id))

    @router.post('/task/{task_id}/regenerate-summary', response_model=SourceRequestReceipt)
    def regenerate(task_id: str, body: SummaryConfirmation, background_tasks: BackgroundTasks,
                   response: Response, user=Depends(principal)):
        response.headers['Cache-Control'] = 'private, no-store'
        return service.accept(user.user_id, task_id, body, background_tasks, note_service,
                              active=active(task_id))

    return router
