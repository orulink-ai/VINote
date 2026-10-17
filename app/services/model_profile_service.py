from typing import Optional

from fastapi import HTTPException

from app.config import settings
from app.models.model_profile import (
    ModelProfileCreateRequest,
    ModelProfileResponse,
    ModelProfileTestRequest,
    ModelProfileTestResponse,
    ModelProfileUpdateRequest,
    ResolvedLLMConfig,
)
from app.services.model_profile_connection_service import ModelProfileConnectionService
from app.services.model_profile_repository import ModelProfileRepository


class ModelProfileService:
    def __init__(
        self,
        repository: ModelProfileRepository | None = None,
        connection_service: ModelProfileConnectionService | None = None,
    ):
        self.repository = repository or ModelProfileRepository()
        self.connection_service = connection_service or ModelProfileConnectionService()

    def list_profiles(self, user_id: str) -> list[ModelProfileResponse]:
        from app.services.vilab_cloud_service import VILabCloudService

        cloud = VILabCloudService().status(user_id)
        if cloud["mode"] == "cloud":
            return [ModelProfileResponse(
                id="vilab-cloud", name="VILab · " + (cloud["llm_model"] or "待选择云端模型"),
                provider="openai-compatible", model_name=cloud["llm_model"], base_url=settings.vilab_server_url,
                api_key_hint="", is_default=True, is_active=True,
            )]
        return self.repository.list_profiles(user_id)

    def create_profile(self, user_id: str, payload: ModelProfileCreateRequest) -> ModelProfileResponse:
        return self.repository.create_profile(user_id, payload)

    def update_profile(self, user_id: str, profile_id: str, payload: ModelProfileUpdateRequest) -> ModelProfileResponse:
        return self.repository.update_profile(user_id, profile_id, payload)

    def reveal_api_key(self, user_id: str, profile_id: str) -> str:
        record = self.repository.get_profile_record(user_id, profile_id)
        return self.repository.decrypt_api_key(record.api_key_encrypted)

    def delete_profile(self, user_id: str, profile_id: str) -> None:
        current = self.repository.delete_profile(user_id, profile_id)
        if current.is_default:
            remaining = self.repository.get_latest_active_profile(user_id)
            if remaining:
                self.repository.set_default_profile(user_id, remaining.id)

    def set_default_profile(self, user_id: str, profile_id: str) -> ModelProfileResponse:
        return self.repository.set_default_profile(user_id, profile_id)

    def resolve_llm_config(
        self,
        *,
        user_id: Optional[str],
        model_profile_id: Optional[str],
        model_name: Optional[str],
        api_key: Optional[str],
        base_url: Optional[str],
    ) -> Optional[ResolvedLLMConfig]:
        if model_profile_id:
            if not user_id:
                raise HTTPException(status_code=401, detail="Authentication required for model profiles")
            record = self.repository.get_profile_record(user_id, model_profile_id)
            if not record.is_active:
                raise HTTPException(status_code=400, detail="Selected model profile is inactive")
            return ResolvedLLMConfig(
                provider=record.provider,
                base_url=record.base_url,
                model_name=record.model_name,
                api_key=self.repository.decrypt_api_key(record.api_key_encrypted),
            )

        if user_id:
            default_profile = self.repository.get_default_profile(user_id)
            if default_profile:
                return ResolvedLLMConfig(
                    provider=default_profile.provider,
                    base_url=default_profile.base_url,
                    model_name=default_profile.model_name,
                    api_key=self.repository.decrypt_api_key(default_profile.api_key_encrypted),
                )

        if model_name or api_key or base_url:
            return ResolvedLLMConfig(
                provider=settings.llm_provider,
                base_url=base_url or settings.llm_base_url,
                model_name=model_name or settings.llm_model,
                api_key=api_key or settings.llm_api_key,
            )

        return None

    def test_connection(self, payload: ModelProfileTestRequest) -> ModelProfileTestResponse:
        return self.connection_service.test_connection(payload)

    def test_saved_profile(self, user_id: str, profile_id: str) -> ModelProfileTestResponse:
        record = self.repository.get_profile_record(user_id, profile_id)
        return self.connection_service.test_connection(
            ModelProfileTestRequest(
                provider=record.provider,
                base_url=record.base_url,
                model_name=record.model_name,
                api_key=self.repository.decrypt_api_key(record.api_key_encrypted),
            )
        )
