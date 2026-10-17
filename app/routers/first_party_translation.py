"""Authenticated, stateless HTTPS Streamable HTTP MCP translation endpoint."""
import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app.models.first_party_translation import ORIGIN, TOOL, TOOL_NAME
from app.routers.feishu import principal
from app.routers.mcp_connections import MCPRoute, bearer, no_store
from app.services import first_party_translation_service as service
from app.services.integration_proxy import proxy_integration
from app.services.mcp_connection_service import PROTOCOLS

BASE = "/api/mcp-first-party/translation"
router = APIRouter(prefix="/mcp-first-party/translation", tags=["first-party-translation"],
                   route_class=MCPRoute, dependencies=[Depends(no_store)])


@router.get("/receipts/{run_id}")
def receipt(run_id: str, identity=Depends(principal)):
    path = "/api/mcp-connections/first-party/translation/receipts/" + quote(run_id, safe="")
    remote, result = proxy_integration(identity, "GET", path)
    return result if remote else service.get_receipt(identity[0], run_id)


def dispatch(body, owner, token, run_id):
    method, params = body.get("method"), body.get("params", {})
    rpc_id = body.get("id")
    if body.get("jsonrpc") != "2.0" or not isinstance(method, str) or not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
    if method == "notifications/initialized" and "id" not in body:
        return None
    if not isinstance(rpc_id, (str, int)) or isinstance(rpc_id, bool):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Request id required"}}
    if method == "initialize":
        protocol = params.get("protocolVersion")
        result = {"protocolVersion": protocol if protocol in PROTOCOLS else PROTOCOLS[0],
                  "capabilities": {"tools": {}},
                  "serverInfo": {"name": "VINote Cloud Translation MCP", "version": "1.0.0"}}
    elif method == "tools/list":
        if not service.provider_metadata()["configured"]:
            raise HTTPException(503, {"code": "provider_not_configured", "message": "VINote 云模型服务尚未配置"})
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        if params.get("name") != TOOL_NAME or not isinstance(params.get("arguments"), dict) or not run_id:
            raise HTTPException(422, {"code": "invalid_call", "message": "需要原确认运行与翻译参数"})
        result = service.call_translation(owner, run_id, params["arguments"], token)
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


@router.post("")
async def protocol(request: Request, identity=Depends(principal)):
    token = bearer(request)
    if not token or identity[1] is not None:
        raise HTTPException(401, {"code": "session_required", "message": "需要当前已验证的云会话"})
    origin = request.headers.get("Origin")
    if origin and origin != ORIGIN.split("/vinote-api")[0]:
        raise HTTPException(403, {"code": "invalid_origin", "message": "仅接受官方 Origin 的浏览器请求"})
    if request.headers.get("MCP-Protocol-Version", PROTOCOLS[0]) not in PROTOCOLS:
        raise HTTPException(400, {"code": "unsupported_protocol", "message": "不支持的 MCP 协议版本"})
    try:
        body = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, {"code": "invalid_request", "message": "无效的 MCP 请求"}) from None
    if not isinstance(body, dict):
        raise HTTPException(422, {"code": "invalid_request", "message": "不支持批量 MCP 请求"})
    result = await run_in_threadpool(dispatch, body, identity[0], token,
                                   request.headers.get("X-VINote-MCP-Run-Id"))
    headers = {"Cache-Control": "no-store"}
    return Response(status_code=202, headers=headers) if result is None else JSONResponse(result, headers=headers)
