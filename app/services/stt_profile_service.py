import importlib.util
from typing import Optional

from fastapi import HTTPException

from app.config import settings
from app.services.task_model_source import verify_stt_result
from app.models.stt_profile import (
    GROQ_STT_BASE_URL,
    LocalSTTSupportStatus,
    STTProfileCreateRequest,
    STTProfileRecord,
    STTProfileResponse,
    STTProfileUpdateRequest,
    STTProviderType,
    ResolvedSTTConfig,
)
from app.services.stt_profile_repository import STTProfileRepository


class STTProfileService:
    def __init__(self, repository: STTProfileRepository | None = None):
        self.repository = repository or STTProfileRepository()

    @staticmethod
    def _clean_optional(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @staticmethod
    def _local_support_install_command() -> str:
        return "pip install -r requirements.local-transcribers.txt"

    def get_local_support_status(self) -> LocalSTTSupportStatus:
        installed = importlib.util.find_spec("faster_whisper") is not None
        return LocalSTTSupportStatus(
            installed=installed,
            install_command=self._local_support_install_command(),
            message=(
                "本地 STT 支持已安装。所选模型可能会在首次使用时自动下载。"
                if installed
                else "本地 STT 支持尚未安装。"
            ),
        )

    def _normalize_fields(
        self,
        *,
        provider: STTProviderType,
        model_name: str | None,
        base_url: str | None,
        api_key: str | None,
        language: str | None,
        device: str | None,
        compute_type: str | None,
        use_gpu: bool | None,
    ) -> dict[str, object]:
        model_name = self._clean_optional(model_name)
        base_url = self._clean_optional(base_url)
        api_key = self._clean_optional(api_key)
        language = self._clean_optional(language)
        device = self._clean_optional(device)
        compute_type = self._clean_optional(compute_type)

        def reject(field_name: str):
            raise HTTPException(status_code=400, detail=f"{field_name} is not supported for provider `{provider}`")

        if provider == "vliab-server":
            from urllib.parse import urlparse

            if not base_url or urlparse(base_url).scheme not in {"http", "https"} or not urlparse(base_url).netloc:
                raise HTTPException(status_code=400, detail="A valid HTTP base_url is required for vliab-server")
            if not api_key:
                raise HTTPException(status_code=400, detail="api_key is required for vliab-server")
            for field, value in [("device", device), ("compute_type", compute_type), ("use_gpu", use_gpu)]:
                if value is not None:
                    reject(field)
            return dict(provider=provider, model_name=model_name, base_url=base_url.rstrip("/"),
                        api_key=api_key, language=language, device=None, compute_type=None, use_gpu=None)

        if provider == "groq":
            if not model_name:
                raise HTTPException(status_code=400, detail="model_name is required for provider `groq`")
            if not api_key:
                raise HTTPException(status_code=400, detail="api_key is required for provider `groq`")
            if base_url:
                reject("base_url")
            if device:
                reject("device")
            if compute_type:
                reject("compute_type")
            if use_gpu is not None:
                reject("use_gpu")
            return {
                "provider": provider,
                "model_name": model_name,
                "base_url": GROQ_STT_BASE_URL,
                "api_key": api_key,
                "language": language,
                "device": None,
                "compute_type": None,
                "use_gpu": None,
            }

        if provider == "whisper":
            if not model_name:
                raise HTTPException(status_code=400, detail="model_name is required for provider `whisper`")
            if not device:
                raise HTTPException(status_code=400, detail="device is required for provider `whisper`")
            if base_url:
                reject("base_url")
            if api_key:
                reject("api_key")
            if language:
                reject("language")
            if compute_type:
                reject("compute_type")
            if use_gpu is not None:
                reject("use_gpu")
            return {
                "provider": provider,
                "model_name": model_name,
                "base_url": None,
                "api_key": None,
                "language": None,
                "device": device,
                "compute_type": None,
                "use_gpu": None,
            }

        if provider == "faster-whisper":
            if not model_name:
                raise HTTPException(status_code=400, detail="model_name is required for provider `faster-whisper`")
            if not device:
                raise HTTPException(status_code=400, detail="device is required for provider `faster-whisper`")
            if not compute_type:
                raise HTTPException(status_code=400, detail="compute_type is required for provider `faster-whisper`")
            if base_url:
                reject("base_url")
            if api_key:
                reject("api_key")
            if use_gpu is not None:
                reject("use_gpu")
            return {
                "provider": provider,
                "model_name": model_name,
                "base_url": None,
                "api_key": None,
                "language": language,
                "device": device,
                "compute_type": compute_type,
                "use_gpu": None,
            }

        if provider == "sensevoice":
            if not base_url:
                raise HTTPException(status_code=400, detail="base_url is required for provider `sensevoice`")
            if not language:
                raise HTTPException(status_code=400, detail="language is required for provider `sensevoice`")
            if model_name:
                reject("model_name")
            if api_key:
                reject("api_key")
            if device:
                reject("device")
            if compute_type:
                reject("compute_type")
            if use_gpu is not None:
                reject("use_gpu")
            return {
                "provider": provider,
                "model_name": None,
                "base_url": base_url,
                "api_key": None,
                "language": language,
                "device": None,
                "compute_type": None,
                "use_gpu": None,
            }

        if not model_name:
            raise HTTPException(status_code=400, detail="model_name is required for provider `sensevoice-local`")
        if not language:
            raise HTTPException(status_code=400, detail="language is required for provider `sensevoice-local`")
        if use_gpu is None:
            raise HTTPException(status_code=400, detail="use_gpu is required for provider `sensevoice-local`")
        if base_url:
            reject("base_url")
        if api_key:
            reject("api_key")
        if device:
            reject("device")
        if compute_type:
            reject("compute_type")
        return {
            "provider": provider,
            "model_name": model_name,
            "base_url": None,
            "api_key": None,
            "language": language,
            "device": "cuda" if use_gpu else "cpu",
            "compute_type": None,
            "use_gpu": use_gpu,
        }

    def _build_resolved_config(self, record: STTProfileRecord) -> ResolvedSTTConfig:
        language = record.language
        if record.provider in {"groq", "whisper", "faster-whisper"} and language and language.lower() == "auto":
            language = None
        return ResolvedSTTConfig(
            provider=record.provider,
            model_name=record.model_name,
            base_url=record.base_url,
            api_key=self.repository.decrypt_api_key(record.api_key_encrypted),
            language=language,
            device=record.device,
            compute_type=record.compute_type,
            use_gpu=record.use_gpu,
        )

    def _build_env_default_config(self) -> ResolvedSTTConfig:
        provider = settings.transcriber_type.lower()
        if provider == "groq":
            return ResolvedSTTConfig(
                provider="groq",
                model_name="whisper-large-v3-turbo",
                base_url=GROQ_STT_BASE_URL,
                api_key=settings.groq_api_key or None,
            )
        if provider == "whisper":
            return ResolvedSTTConfig(
                provider="whisper",
                model_name=settings.whisper_model_size,
                device=settings.whisper_device,
            )
        if provider == "faster-whisper":
            return ResolvedSTTConfig(
                provider="faster-whisper",
                model_name=settings.whisper_model_size,
                device=settings.whisper_device,
                compute_type=settings.faster_whisper_compute_type,
            )
        if provider == "sensevoice":
            return ResolvedSTTConfig(
                provider="sensevoice",
                base_url=settings.sensevoice_base_url,
                language=settings.sensevoice_language,
            )
        if provider == "sensevoice-local":
            return ResolvedSTTConfig(
                provider="sensevoice-local",
                model_name=settings.sensevoice_model_size,
                language=settings.sensevoice_language,
                device="cuda" if settings.sensevoice_use_gpu else "cpu",
                use_gpu=settings.sensevoice_use_gpu,
            )
        raise ValueError(f"Unsupported transcriber type: {provider}")

    def list_profiles(self, user_id: str) -> list[STTProfileResponse]:
        from app.services.vilab_cloud_service import VILabCloudService

        cloud = VILabCloudService().status(user_id)
        if cloud["mode"] == "cloud":
            return [STTProfileResponse(
                id="vilab-cloud", name="VILab · " + (cloud["asr_model"] or "待选择云端模型"),
                provider="vliab-server", model_name=cloud["asr_model"], base_url=settings.vilab_server_url,
                api_key_hint="", is_default=True, is_active=True,
            )]
        return self.repository.list_profiles(user_id)

    def create_profile(self, user_id: str, payload: STTProfileCreateRequest) -> STTProfileResponse:
        normalized = self._normalize_fields(
            provider=payload.provider,
            model_name=payload.model_name,
            base_url=payload.base_url,
            api_key=payload.api_key,
            language=payload.language,
            device=payload.device,
            compute_type=payload.compute_type,
            use_gpu=payload.use_gpu,
        )
        return self.repository.create_profile(
            user_id,
            STTProfileCreateRequest(
                name=payload.name.strip(),
                is_default=payload.is_default,
                is_active=payload.is_active,
                **normalized,
            ),
        )

    def update_profile(self, user_id: str, profile_id: str, payload: STTProfileUpdateRequest) -> STTProfileResponse:
        current = self.repository.get_profile_record(user_id, profile_id)
        provider = payload.provider or current.provider
        provider_changed = payload.provider is not None and payload.provider != current.provider
        api_key = (
            payload.api_key
            if payload.api_key is not None
            else None if provider_changed else self.repository.decrypt_api_key(current.api_key_encrypted)
        )
        normalized = self._normalize_fields(
            provider=provider,
            model_name=payload.model_name if payload.model_name is not None else None if provider_changed else current.model_name,
            base_url=payload.base_url if payload.base_url is not None else None if provider_changed else current.base_url,
            api_key=api_key,
            language=payload.language if payload.language is not None else None if provider_changed else current.language,
            device=payload.device if payload.device is not None else None if provider_changed else current.device,
            compute_type=payload.compute_type if payload.compute_type is not None else None if provider_changed else current.compute_type,
            use_gpu=payload.use_gpu if payload.use_gpu is not None else None if provider_changed else current.use_gpu,
        )
        update_payload: dict[str, object] = dict(normalized)
        if payload.name is not None:
            update_payload["name"] = payload.name.strip()
        if payload.is_default is not None:
            update_payload["is_default"] = payload.is_default
        if payload.is_active is not None:
            update_payload["is_active"] = payload.is_active
        return self.repository.update_profile(
            user_id,
            profile_id,
            STTProfileUpdateRequest(**update_payload),
        )

    def reveal_api_key(self, user_id: str, profile_id: str) -> str:
        record = self.repository.get_profile_record(user_id, profile_id)
        return self.repository.decrypt_api_key(record.api_key_encrypted)

    def delete_profile(self, user_id: str, profile_id: str) -> None:
        current = self.repository.delete_profile(user_id, profile_id)
        if current.is_default:
            remaining = self.repository.get_latest_active_profile(user_id)
            if remaining:
                self.repository.set_default_profile(user_id, remaining.id)

    def set_default_profile(self, user_id: str, profile_id: str) -> STTProfileResponse:
        return self.repository.set_default_profile(user_id, profile_id)

    @verify_stt_result
    def resolve_config(self, *, user_id: Optional[str], stt_profile_id: Optional[str]) -> ResolvedSTTConfig:
        if user_id:
            from app.services.vilab_cloud_service import VILabCloudService

            service = VILabCloudService()
            cloud = service.status(user_id)
            if cloud["mode"] == "cloud" and cloud["asr_model"]:
                return ResolvedSTTConfig(provider="vliab-server", base_url=cloud.get("server_url") or settings.vilab_server_url,
                                         model_name=cloud["asr_model"], cloud_user_id=user_id)
            if cloud["mode"] == "cloud":
                raise HTTPException(400, "云端模式尚未选择转写模型，请在设置中选择，或切换到本地模式")
            if stt_profile_id == "vilab-cloud":
                stt_profile_id = None
        if stt_profile_id:
            if not user_id:
                raise HTTPException(status_code=401, detail="Authentication required for STT profiles")
            record = self.repository.get_profile_record(user_id, stt_profile_id)
            if not record.is_active:
                raise HTTPException(status_code=400, detail="Selected STT profile is inactive")
            return self._build_resolved_config(record)

        if user_id:
            default_profile = self.repository.get_default_profile(user_id)
            if default_profile:
                return self._build_resolved_config(default_profile)

        return self._build_env_default_config()
