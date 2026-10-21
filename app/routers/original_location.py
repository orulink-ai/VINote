"""Desktop Cookie-only locations. No request path/URL, cloud handoff or writes."""
from ipaddress import ip_address

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.config import settings
from app.services.auth_service import get_current_user
from app.services.original_location import OriginalLocationService

HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


class LocalPathRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def no_store(request):
            try:
                response = await handler(request)
                response.headers.update(HEADERS)
                return response
            except HTTPException as error:
                error.headers = {**(error.headers or {}), **HEADERS}
                raise
        return no_store


def desktop_cookie(request: Request):
    if not settings.desktop_runtime or settings.workspace_cloud_runtime or settings.content_cloud_runtime:
        raise HTTPException(404, "此能力仅在原文件所在桌面可用")
    try:
        if request.client is None or not ip_address(request.client.host).is_loopback:
            raise ValueError()
    except ValueError:
        raise HTTPException(403, "请在原文件所在电脑操作") from None
    if request.query_params:
        raise HTTPException(422, "此端点仅接受已保存对象标识")
    if "authorization" in request.headers:
        raise HTTPException(401, "此能力仅接受桌面 Cookie 会话")
    if not request.cookies.get(settings.auth_cookie_name):
        raise HTTPException(401, "Authentication required")
    # Deliberately do not accept Bearer/mobile credentials or proxy to account
    # services. Reuse the desktop Cookie identity and current-project check.
    return get_current_user(request, credentials=None)


router = APIRouter(tags=["original-location"], route_class=LocalPathRoute)


@router.get("/files/{identifier}/local-path", include_in_schema=False)
def file_location(identifier: str, user=Depends(desktop_cookie)):
    return JSONResponse(OriginalLocationService().file(user.user_id, identifier), headers=HEADERS)


@router.get("/notes/{note_id}/media/local-path", include_in_schema=False)
def note_location(note_id: str, user=Depends(desktop_cookie)):
    return JSONResponse(OriginalLocationService().note(user.user_id, note_id), headers=HEADERS)


@router.get("/task/{task_id}/original/local-path", include_in_schema=False)
def task_location(task_id: str, user=Depends(desktop_cookie)):
    return JSONResponse(OriginalLocationService().task(user.user_id, task_id), headers=HEADERS)
