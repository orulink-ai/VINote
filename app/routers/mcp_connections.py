"""Remote MCP API; authentication is identical for desktop and mobile."""
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from app.models.mcp_connections import ConnectionCreate, ConnectionPatch, InvokeRequest, ToolPatch, request_body
from app.routers.feishu import principal
from app.services.integration_proxy import proxy_integration
from app.services.mcp_connection_service import MCPConnectionService
from app.models.first_party_translation import ProvisionRequest


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


class MCPRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded_handler(request):
            # Bound bytes before JSON parsing and never echo submitted secrets in
            # FastAPI's default validation errors (which include invalid inputs).
            if request.method in ("POST", "PATCH"):
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 512 * 1024:
                        raise HTTPException(413, {"code": "request_too_large", "message": "请求正文超过限制"},
                                            headers={"Cache-Control": "no-store"})
                request._body = bytes(body)
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(422, {"code": "invalid_request", "message": "请求参数格式无效，请检查输入"},
                                    headers={"Cache-Control": "no-store"}) from None
        return bounded_handler


router = APIRouter(prefix="/mcp-connections", tags=["mcp-connections"],
                   route_class=MCPRoute, dependencies=[Depends(no_store)])
service = MCPConnectionService()
BASE = "/api/mcp-connections"


def bearer(request):
    auth = request.headers.get("Authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else None


@router.post("/first-party/translation", status_code=201)
def provision_translation(request: Request, payload: ProvisionRequest, identity=Depends(principal)):
    remote, result = proxy_integration(identity, "POST", BASE + "/first-party/translation", {})
    if remote:
        return result
    from app.services.first_party_translation_service import provision
    return provision(identity[0], bearer(request))


@router.get("/first-party/translation/receipts/{run_id}")
def translation_receipt(run_id: str, identity=Depends(principal)):
    path = BASE + "/first-party/translation/receipts/" + quote(run_id, safe="")
    remote, result = proxy_integration(identity, "GET", path)
    if remote:
        return result
    from app.services.first_party_translation_service import get_receipt
    return get_receipt(identity[0], run_id)


@router.get("/first-party/translation/models")
def translation_models(request: Request, identity=Depends(principal)):
    remote, result = proxy_integration(identity, "GET", BASE + "/first-party/translation/models")
    if remote:
        return result
    from app.services.first_party_translation_service import model_options
    return model_options(identity[0], bearer(request))


def connection_path(connection_id, suffix=""):
    return BASE + "/" + quote(connection_id, safe="") + suffix


@router.get("/capabilities")
def capabilities(identity=Depends(principal)):
    remote, result = proxy_integration(identity, "GET", BASE + "/capabilities")
    return result if remote else service.capabilities()


@router.get("/runs")
def runs(connectionId: str | None = Query(default=None, max_length=36),
         limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0, le=100000),
         identity=Depends(principal)):
    query = {"limit": limit, "offset": offset}
    if connectionId:
        query["connectionId"] = connectionId
    remote, result = proxy_integration(identity, "GET", BASE + "/runs?" + urlencode(query))
    return result if remote else service.runs(identity[0], connectionId, limit, offset)


@router.get("/runs/by-request/{request_id}")
def get_run_by_request(request_id: str, identity=Depends(principal)):
    path = BASE + "/runs/by-request/" + quote(request_id, safe="")
    remote, result = proxy_integration(identity, "GET", path)
    return result if remote else service.get_run_by_request(identity[0], request_id)


@router.get("/runs/{run_id}")
def get_run(run_id: str, identity=Depends(principal)):
    remote, result = proxy_integration(identity, "GET", BASE + "/runs/" + quote(run_id, safe=""))
    return result if remote else service.get_run(identity[0], run_id)


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, identity=Depends(principal)):
    remote, result = proxy_integration(identity, "POST", BASE + "/runs/" + quote(run_id, safe="") + "/cancel")
    return result if remote else service.cancel(identity[0], run_id)


@router.get("")
def list_connections(identity=Depends(principal)):
    remote, result = proxy_integration(identity, "GET", BASE)
    return result if remote else service.list_connections(identity[0])


@router.post("", status_code=201)
def create(payload: ConnectionCreate, identity=Depends(principal)):
    body = request_body(payload)
    remote, result = proxy_integration(identity, "POST", BASE, body)
    return result if remote else service.create(identity[0], body)


@router.patch("/{connection_id}")
def patch(connection_id: str, payload: ConnectionPatch, identity=Depends(principal)):
    body = request_body(payload, exclude_unset=True)
    remote, result = proxy_integration(identity, "PATCH", connection_path(connection_id), body)
    return result if remote else service.patch(identity[0], connection_id, body)


@router.delete("/{connection_id}")
def delete(connection_id: str, identity=Depends(principal)):
    remote, result = proxy_integration(identity, "DELETE", connection_path(connection_id))
    return result if remote else service.delete(identity[0], connection_id)


@router.post("/{connection_id}/discover")
def discover(connection_id: str, request: Request, identity=Depends(principal)):
    remote, result = proxy_integration(identity, "POST", connection_path(connection_id, "/discover"))
    return result if remote else service.discover(identity[0], connection_id, session_bearer=bearer(request))


@router.get("/{connection_id}/tools")
def tools(connection_id: str, identity=Depends(principal)):
    remote, result = proxy_integration(identity, "GET", connection_path(connection_id, "/tools"))
    return result if remote else service.tools(identity[0], connection_id)


@router.patch("/{connection_id}/tools")
def patch_tool(connection_id: str, payload: ToolPatch, identity=Depends(principal)):
    body = request_body(payload)
    remote, result = proxy_integration(identity, "PATCH", connection_path(connection_id, "/tools"), body)
    return result if remote else service.patch_tool(identity[0], connection_id, payload.name, payload.enabled)


@router.post("/{connection_id}/invoke")
def invoke(connection_id: str, payload: InvokeRequest, request: Request, identity=Depends(principal)):
    body = request_body(payload)
    remote, result = proxy_integration(identity, "POST", connection_path(connection_id, "/invoke"), body)
    return result if remote else service.invoke(identity[0], connection_id, body, session_bearer=bearer(request))
