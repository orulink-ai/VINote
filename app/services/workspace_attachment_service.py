"""Account-private content images. Never accept original audio/video."""
import hashlib
import re
import warnings
from io import BytesIO
from urllib.parse import quote, urlsplit

import httpx
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import session_scope
from app.models.workspace_attachment import WorkspaceAttachmentDB

MAX_BYTES = 5 * 1024 * 1024
REFERENCE = re.compile(r"attachment://([a-f0-9]{64})")
TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


class WorkspaceAttachmentService:
    @property
    def cloud(self):
        return bool(settings.workspace_storage_key and settings.workspace_storage_url)

    def _object(self, owner, identifier):
        prefix = hashlib.sha256(owner.encode()).hexdigest()
        return f"{prefix}/{identifier}"

    def _local(self, owner, identifier):
        # A 128-bit namespace keeps Windows paths bounded. Database ownership is
        # still checked using the complete identity before every read.
        prefix = hashlib.sha256(owner.encode()).hexdigest()[:32]
        return settings.data_dir / "workspace-attachments" / prefix / identifier

    def _storage(self, method, path, **kwargs):
        if urlsplit(settings.workspace_storage_url).scheme != "https":
            raise HTTPException(503, "私有附件存储尚未配置")
        try:
            with httpx.stream(
                method, settings.workspace_storage_url + "/storage/v1/" + path,
                headers={"Authorization": "Bearer " + settings.workspace_storage_key,
                         "apikey": settings.workspace_storage_key, **kwargs.pop("headers", {})},
                timeout=30, follow_redirects=False, **kwargs,
            ) as stream:
                if not stream.is_success:
                    raise HTTPException(502, "附件存储未确认成功，请重试")
                limit = MAX_BYTES if method == "GET" and path.startswith("object/") else 65536
                chunks, size = [], 0
                for chunk in stream.iter_bytes(65536):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(502, "附件存储返回内容超过限制")
                    chunks.append(chunk)
                response = httpx.Response(stream.status_code, content=b"".join(chunks), headers=stream.headers)
        except httpx.RequestError:
            raise HTTPException(502, "附件存储暂不可用，内容已保留，请重试") from None
        if not response.is_success:
            raise HTTPException(502, "附件存储未确认成功，请重试")
        return response

    def _json(self, response):
        try:
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except ValueError:
            raise HTTPException(502, "附件存储回执无效，请重试读取") from None

    def _bucket(self):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", settings.workspace_storage_bucket):
            raise HTTPException(503, "附件存储配置无效")
        return quote(settings.workspace_storage_bucket, safe="")

    def upload(self, owner, data):
        if settings.workspace_cloud_runtime and not self.cloud:
            raise HTTPException(503, "云端私有附件存储尚未配置")
        if not data or len(data) > MAX_BYTES:
            raise HTTPException(413, "内容图片需要在 5 MB 以内，不能上传原始音视频")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as image:
                    content_type = TYPES.get(image.format)
                    if not content_type or image.width * image.height > 16000000 or getattr(image, "n_frames", 1) != 1:
                        raise ValueError("unsupported image")
                    image.verify()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise HTTPException(422, "仅支持有效的静态 PNG、JPEG、WebP 内容图片") from None
        identifier = hashlib.sha256(data).hexdigest()
        with session_scope() as db:
            existing = db.get(WorkspaceAttachmentDB, (owner, identifier))
        if not existing:
            object_key = self._object(owner, identifier)
            if self.cloud:
                # Verify the bucket is private; never silently create/publicize a bucket.
                bucket = self._json(self._storage("GET", "bucket/" + self._bucket()))
                if bucket.get("public") is not False:
                    raise HTTPException(503, "正文附件必须使用私有存储桶")
                self._storage("POST", f"object/{self._bucket()}/{object_key}", content=data,
                              headers={"Content-Type": content_type, "x-upsert": "true"})
            else:
                target = self._local(owner, identifier)
                target.parent.mkdir(parents=True, exist_ok=True)
                # Content-addressed files make retry and parallel writers safe.
                target.write_bytes(data)
            try:
                with session_scope() as db:
                    db.add(WorkspaceAttachmentDB(owner=owner, id=identifier,
                                                 content_type=content_type, size_bytes=len(data)))
            except IntegrityError:
                with session_scope() as db:
                    if not db.get(WorkspaceAttachmentDB, (owner, identifier)):
                        raise
        return {"id": identifier, "reference": "attachment://" + identifier,
                "content_type": content_type, "size_bytes": len(data)}

    def _owned(self, owner, identifier):
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise HTTPException(404, "找不到内容附件")
        with session_scope() as db:
            row = db.get(WorkspaceAttachmentDB, (owner, identifier))
            if not row:
                raise HTTPException(404, "找不到内容附件")
            return {"content_type": row.content_type, "size_bytes": row.size_bytes}

    def read(self, owner, identifier):
        row = self._owned(owner, identifier)
        if self.cloud:
            data = self._storage("GET", f"object/{self._bucket()}/{self._object(owner, identifier)}").content
        else:
            target = self._local(owner, identifier)
            if not target.is_file() or target.is_symlink():
                raise HTTPException(404, "附件文件暂不可用")
            data = target.read_bytes()
        if len(data) != row["size_bytes"] or hashlib.sha256(data).hexdigest() != identifier:
            raise HTTPException(502, "附件完整性核验失败，请重试")
        return data, row["content_type"]

    def access(self, owner, identifier):
        self._owned(owner, identifier)
        if not self.cloud:
            return {"url": f"/api/workspace/attachments/{identifier}/content", "expires_in": 0, "authenticated": True}
        payload = self._json(self._storage("POST", f"object/sign/{self._bucket()}/{self._object(owner, identifier)}",
                                          json={"expiresIn": 300}))
        signed = payload.get("signedURL", "")
        expected = f"/object/sign/{self._bucket()}/{self._object(owner, identifier)}?"
        if not isinstance(signed, str) or not signed.startswith(expected) or ".." in signed or "\\" in signed:
            raise HTTPException(502, "附件访问地址无效")
        return {"url": settings.workspace_storage_url + "/storage/v1" + signed,
                "expires_in": 300, "authenticated": False}

    def validate_references(self, owner, bodies):
        for identifier in set(REFERENCE.findall("\n".join(bodies))):
            try:
                self._owned(owner, identifier)
            except HTTPException:
                raise HTTPException(422, "正文附件尚未上传或不属于当前账号，请保留内容后重试") from None
