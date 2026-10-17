"""Authenticated, ephemeral text extraction for clients' selected model service."""
import json

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.datastructures import UploadFile

from app.services.generation_auth_service import get_generation_user
from app.services import text_extraction_service as extraction

router = APIRouter(tags=['content-extraction'])


class ExtractUrl(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    url: str = Field(min_length=1, max_length=8192)


def bound_body(request, maximum):
    try:
        declared = int(request.headers.get('content-length', '0'))
        if declared < 0 or declared > maximum:
            raise ValueError()
    except ValueError:
        raise HTTPException(413, '提取请求超过大小限制') from None
    receive = request.receive
    count = 0

    async def limited_receive():
        nonlocal count
        message = await receive()
        if message['type'] == 'http.request':
            count += len(message.get('body', b''))
            if count > maximum:
                raise HTTPException(413, '提取请求超过大小限制')
        return message

    request._receive = limited_receive


@router.post('/content-service/extract-url')
async def extract_url(request: Request, response: Response, user=Depends(get_generation_user)):
    response.headers['Cache-Control'] = 'no-store'
    bound_body(request, 32768)
    try:
        payload = ExtractUrl.model_validate(json.loads(await request.body()))
    except (ValueError, ValidationError):
        raise HTTPException(422, '仅接受一个有效公开网页或文档链接，不接受模型配置') from None
    try:
        return await anyio.to_thread.run_sync(lambda: extraction.extract_url(payload.url))
    except (ValueError, RecursionError):
        raise HTTPException(422, '无法提取此来源：仅支持公开网页/PDF/DOCX，视频请在设备读取；请检查链接、访问权限和大小') from None


@router.post('/content-service/extract-file')
async def extract_file(request: Request, response: Response, user=Depends(get_generation_user)):
    response.headers['Cache-Control'] = 'no-store'
    bound_body(request, extraction.MAX_BYTES + 65536)
    async with request.form(max_files=1, max_fields=0) as form:
        if len(form) != 1 or len(form.getlist('file')) != 1:
            raise HTTPException(422, '仅接受一个file文件，不接受其他配置')
        upload = form.get('file')
        if not isinstance(upload, UploadFile):
            raise HTTPException(422, '请选择来源文件')
        if upload.size is not None and not 0 < upload.size <= extraction.MAX_BYTES:
            raise HTTPException(413, '来源文件必须非空且不超过20 MiB')
        data = await upload.read(extraction.MAX_BYTES + 1)
        if len(data) > extraction.MAX_BYTES:
            raise HTTPException(413, '来源文件超过20 MiB')
        try:
            return await anyio.to_thread.run_sync(lambda: extraction.extract_file(upload.filename, data))
        except (ValueError, RecursionError):
            raise HTTPException(422, '文件无法提取，请检查格式和正文长度；仅支持PDF/DOCX及UTF-8文字或字幕') from None
