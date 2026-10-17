import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import desc, select

from app.db import session_scope
from app.db_models import STTProfileDB
from app.models.stt_profile import (
    STTProfileCreateRequest,
    STTProfileRecord,
    STTProfileResponse,
    STTProfileUpdateRequest,
)


class STTProfileRepository:
    def __init__(self):
        self._fernet: Optional[Fernet] = None
        from app.config import settings

        if settings.model_profile_encryption_key:
            digest = hashlib.sha256(settings.model_profile_encryption_key.encode("utf-8")).digest()
            self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def _require_encryption(self):
        if not self._fernet:
            raise HTTPException(status_code=500, detail="MODEL_PROFILE_ENCRYPTION_KEY is not configured")

    def _encrypt_optional(self, value: str | None) -> str | None:
        if not value:
            return None
        self._require_encryption()
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt_api_key(self, value: str | None) -> str:
        if not value:
            return ""
        self._require_encryption()
        return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")

    @staticmethod
    def mask_api_key(api_key: str) -> str:
        if not api_key:
            return ""
        if len(api_key) <= 8:
            return "*" * len(api_key)
        return f"{api_key[:4]}****{api_key[-4:]}"

    @staticmethod
    def to_response(record: STTProfileRecord, api_key_hint: str) -> STTProfileResponse:
        return STTProfileResponse(
            id=record.id,
            name=record.name,
            provider=record.provider,
            model_name=record.model_name,
            base_url=record.base_url,
            api_key_hint=api_key_hint,
            language=record.language,
            device=record.device,
            compute_type=record.compute_type,
            use_gpu=record.use_gpu,
            is_default=record.is_default,
            is_active=record.is_active,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _to_record(row: STTProfileDB) -> STTProfileRecord:
        return STTProfileRecord(
            id=row.id,
            user_id=row.user_id,
            name=row.name,
            provider=row.provider,
            model_name=row.model_name,
            base_url=row.base_url,
            api_key_encrypted=row.api_key_encrypted,
            language=row.language,
            device=row.device,
            compute_type=row.compute_type,
            use_gpu=row.use_gpu,
            is_default=row.is_default,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def list_profiles(self, user_id: str) -> list[STTProfileResponse]:
        with session_scope() as db:
            rows = db.scalars(
                select(STTProfileDB).where(STTProfileDB.user_id == user_id).order_by(desc(STTProfileDB.updated_at))
            ).all()
        return [
            self.to_response(record, self.mask_api_key(self.decrypt_api_key(record.api_key_encrypted)))
            for record in (self._to_record(row) for row in rows)
        ]

    def create_profile(self, user_id: str, payload: STTProfileCreateRequest) -> STTProfileResponse:
        with session_scope() as db:
            if payload.is_default:
                rows = db.scalars(select(STTProfileDB).where(STTProfileDB.user_id == user_id)).all()
                for row in rows:
                    row.is_default = False

            record = STTProfileDB(
                user_id=user_id,
                name=payload.name.strip(),
                provider=payload.provider,
                model_name=payload.model_name.strip() if payload.model_name else None,
                base_url=payload.base_url.strip() if payload.base_url else None,
                api_key_encrypted=self._encrypt_optional(payload.api_key.strip()) if payload.api_key else None,
                language=payload.language.strip() if payload.language else None,
                device=payload.device.strip() if payload.device else None,
                compute_type=payload.compute_type.strip() if payload.compute_type else None,
                use_gpu=payload.use_gpu,
                is_default=payload.is_default,
                is_active=payload.is_active,
            )
            db.add(record)
            db.flush()
            return self.to_response(self._to_record(record), self.mask_api_key(payload.api_key or ""))

    def get_profile_record(self, user_id: str, profile_id: str) -> STTProfileRecord:
        with session_scope() as db:
            row = db.scalar(select(STTProfileDB).where(STTProfileDB.id == profile_id, STTProfileDB.user_id == user_id))
            if not row:
                raise HTTPException(status_code=404, detail="STT profile not found")
            return self._to_record(row)

    def update_profile(self, user_id: str, profile_id: str, payload: STTProfileUpdateRequest) -> STTProfileResponse:
        with session_scope() as db:
            row = db.scalar(select(STTProfileDB).where(STTProfileDB.id == profile_id, STTProfileDB.user_id == user_id))
            if not row:
                raise HTTPException(status_code=404, detail="STT profile not found")
            fields_set = payload.model_fields_set

            if payload.is_default:
                rows = db.scalars(select(STTProfileDB).where(STTProfileDB.user_id == user_id)).all()
                for item in rows:
                    item.is_default = False

            if "name" in fields_set:
                row.name = payload.name.strip() if payload.name else row.name
            if "provider" in fields_set and payload.provider is not None:
                row.provider = payload.provider
            if "model_name" in fields_set:
                row.model_name = payload.model_name.strip() if payload.model_name else None
            if "base_url" in fields_set:
                row.base_url = payload.base_url.strip() if payload.base_url else None
            if "api_key" in fields_set:
                row.api_key_encrypted = self._encrypt_optional(payload.api_key.strip()) if payload.api_key else None
            if "language" in fields_set:
                row.language = payload.language.strip() if payload.language else None
            if "device" in fields_set:
                row.device = payload.device.strip() if payload.device else None
            if "compute_type" in fields_set:
                row.compute_type = payload.compute_type.strip() if payload.compute_type else None
            if "use_gpu" in fields_set:
                row.use_gpu = payload.use_gpu
            if "is_default" in fields_set and payload.is_default is not None:
                row.is_default = payload.is_default
            if "is_active" in fields_set and payload.is_active is not None:
                row.is_active = payload.is_active

            db.flush()
            record = self._to_record(row)
            api_key = self.decrypt_api_key(record.api_key_encrypted)
            if "api_key" in fields_set:
                api_key = payload.api_key.strip() if payload.api_key else ""
            return self.to_response(record, self.mask_api_key(api_key))

    def delete_profile(self, user_id: str, profile_id: str) -> STTProfileRecord:
        with session_scope() as db:
            row = db.scalar(select(STTProfileDB).where(STTProfileDB.id == profile_id, STTProfileDB.user_id == user_id))
            if not row:
                raise HTTPException(status_code=404, detail="STT profile not found")
            current = self._to_record(row)
            db.delete(row)
            return current

    def set_default_profile(self, user_id: str, profile_id: str) -> STTProfileResponse:
        with session_scope() as db:
            rows = db.scalars(select(STTProfileDB).where(STTProfileDB.user_id == user_id)).all()
            target: STTProfileDB | None = None
            for row in rows:
                row.is_default = row.id == profile_id
                if row.id == profile_id:
                    target = row

            if not target:
                raise HTTPException(status_code=404, detail="STT profile not found")

            db.flush()
            record = self._to_record(target)
            return self.to_response(record, self.mask_api_key(self.decrypt_api_key(record.api_key_encrypted)))

    def get_default_profile(self, user_id: str) -> Optional[STTProfileRecord]:
        with session_scope() as db:
            row = db.scalar(
                select(STTProfileDB).where(
                    STTProfileDB.user_id == user_id,
                    STTProfileDB.is_default.is_(True),
                    STTProfileDB.is_active.is_(True),
                )
            )
            return self._to_record(row) if row else None

    def get_latest_active_profile(self, user_id: str) -> Optional[STTProfileRecord]:
        with session_scope() as db:
            row = db.scalar(
                select(STTProfileDB)
                .where(STTProfileDB.user_id == user_id, STTProfileDB.is_active.is_(True))
                .order_by(desc(STTProfileDB.updated_at))
            )
            return self._to_record(row) if row else None
