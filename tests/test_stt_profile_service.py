import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException

from app.config import settings
from app.models.stt_profile import (
    STTProfileCreateRequest,
    STTProfileRecord,
    STTProfileResponse,
    STTProfileUpdateRequest,
)
from app.services.stt_profile_service import STTProfileService


def make_record(
    *,
    profile_id: str = "stt-profile-1",
    provider: str = "groq",
    is_default: bool = True,
    is_active: bool = True,
    model_name: str | None = "whisper-large-v3-turbo",
    base_url: str | None = "https://api.groq.com/openai/v1",
    language: str | None = None,
    device: str | None = None,
    compute_type: str | None = None,
    use_gpu: bool | None = None,
    api_key_encrypted: str | None = "encrypted-key",
) -> STTProfileRecord:
    return STTProfileRecord(
        id=profile_id,
        user_id="user-1",
        name="Primary STT",
        provider=provider,  # type: ignore[arg-type]
        model_name=model_name,
        base_url=base_url,
        api_key_encrypted=api_key_encrypted,
        language=language,
        device=device,
        compute_type=compute_type,
        use_gpu=use_gpu,
        is_default=is_default,
        is_active=is_active,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def make_response(payload, *, profile_id: str = "stt-profile-1") -> STTProfileResponse:
    return STTProfileResponse(
        id=profile_id,
        name=payload.name,
        provider=payload.provider,
        model_name=payload.model_name,
        base_url=payload.base_url,
        api_key_hint="hint",
        language=payload.language,
        device=payload.device,
        compute_type=payload.compute_type,
        use_gpu=payload.use_gpu,
        is_default=payload.is_default,
        is_active=payload.is_active,
    )


class FakeRepository:
    def __init__(self):
        self.created_payload = None
        self.updated_payload = None
        self.deleted_profile = make_record()
        self.latest_active_profile = make_record(profile_id="stt-profile-2", is_default=False)
        self.default_profile = make_record()
        self.profile_record = make_record()
        self.default_set_calls: list[tuple[str, str]] = []

    def list_profiles(self, user_id: str):
        return []

    def create_profile(self, user_id: str, payload):
        self.created_payload = payload
        return make_response(payload)

    def update_profile(self, user_id: str, profile_id: str, payload):
        self.updated_payload = payload
        merged = self.profile_record.model_copy(
            update={
                "name": payload.name if payload.name is not None else self.profile_record.name,
                "provider": payload.provider if payload.provider is not None else self.profile_record.provider,
                "model_name": payload.model_name if "model_name" in payload.model_fields_set else self.profile_record.model_name,
                "base_url": payload.base_url if "base_url" in payload.model_fields_set else self.profile_record.base_url,
                "language": payload.language if "language" in payload.model_fields_set else self.profile_record.language,
                "device": payload.device if "device" in payload.model_fields_set else self.profile_record.device,
                "compute_type": payload.compute_type if "compute_type" in payload.model_fields_set else self.profile_record.compute_type,
                "use_gpu": payload.use_gpu if "use_gpu" in payload.model_fields_set else self.profile_record.use_gpu,
                "is_default": payload.is_default if payload.is_default is not None else self.profile_record.is_default,
                "is_active": payload.is_active if payload.is_active is not None else self.profile_record.is_active,
            }
        )
        self.profile_record = merged
        return make_response(merged, profile_id=profile_id)

    def delete_profile(self, user_id: str, profile_id: str):
        return self.deleted_profile

    def get_latest_active_profile(self, user_id: str):
        return self.latest_active_profile

    def set_default_profile(self, user_id: str, profile_id: str):
        self.default_set_calls.append((user_id, profile_id))
        return make_response(self.latest_active_profile, profile_id=profile_id)

    def get_profile_record(self, user_id: str, profile_id: str):
        return self.profile_record

    def get_default_profile(self, user_id: str):
        return self.default_profile

    def decrypt_api_key(self, value: str | None):
        return "plain-secret" if value else ""


class STTProfileServiceTest(unittest.TestCase):
    def setUp(self):
        # These cases exercise custom profiles, independent of deployment mode.
        mode = patch("app.services.vilab_cloud_service.VILabCloudService.status", return_value={"mode": "local"})
        mode.start()
        self.addCleanup(mode.stop)

    def test_resolve_config_prefers_selected_profile(self):
        repository = FakeRepository()
        service = STTProfileService(repository=repository)

        resolved = service.resolve_config(user_id="user-1", stt_profile_id="stt-profile-1")

        self.assertEqual(resolved.provider, "groq")
        self.assertEqual(resolved.model_name, "whisper-large-v3-turbo")
        self.assertEqual(resolved.api_key, "plain-secret")

    def test_resolve_config_strips_auto_language_for_whisper_family_profiles(self):
        repository = FakeRepository()
        repository.profile_record = make_record(
            provider="faster-whisper",
            model_name="base",
            language="auto",
            device="cpu",
            compute_type="int8",
            api_key_encrypted=None,
        )
        service = STTProfileService(repository=repository)

        resolved = service.resolve_config(user_id="user-1", stt_profile_id="stt-profile-1")

        self.assertEqual(resolved.provider, "faster-whisper")
        self.assertIsNone(resolved.language)

    def test_resolve_config_rejects_inactive_selected_profile(self):
        repository = FakeRepository()
        repository.profile_record = make_record(is_active=False)
        service = STTProfileService(repository=repository)

        with self.assertRaises(HTTPException) as exc:
            service.resolve_config(user_id="user-1", stt_profile_id="stt-profile-1")

        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(exc.exception.detail, "Selected STT profile is inactive")

    def test_resolve_config_falls_back_to_env(self):
        service = STTProfileService(repository=FakeRepository())

        with patch.multiple(
            settings,
            transcriber_type="faster-whisper",
            whisper_model_size="large-v3",
            whisper_device="cuda",
            faster_whisper_compute_type="float16",
        ):
            resolved = service.resolve_config(user_id=None, stt_profile_id=None)

        self.assertEqual(resolved.provider, "faster-whisper")
        self.assertEqual(resolved.model_name, "large-v3")
        self.assertEqual(resolved.device, "cuda")
        self.assertEqual(resolved.compute_type, "float16")

    def test_create_profile_normalizes_groq_fields(self):
        repository = FakeRepository()
        service = STTProfileService(repository=repository)

        response = service.create_profile(
            "user-1",
            STTProfileCreateRequest(
                name="Groq STT",
                provider="groq",
                model_name="whisper-large-v3-turbo",
                api_key="groq-secret",
                language="en",
                is_default=True,
            ),
        )

        self.assertEqual(response.base_url, "https://api.groq.com/openai/v1")
        self.assertIsNotNone(repository.created_payload)
        self.assertEqual(repository.created_payload.base_url, "https://api.groq.com/openai/v1")
        self.assertIsNone(repository.created_payload.device)
        self.assertEqual(repository.created_payload.language, "en")

    def test_update_profile_clears_old_provider_fields_when_provider_changes(self):
        repository = FakeRepository()
        repository.profile_record = make_record(provider="groq")
        service = STTProfileService(repository=repository)

        service.update_profile(
            "user-1",
            "stt-profile-1",
            STTProfileUpdateRequest(
                provider="whisper",
                model_name="small",
                device="cpu",
            ),
        )

        self.assertIsNotNone(repository.updated_payload)
        self.assertEqual(repository.updated_payload.provider, "whisper")
        self.assertEqual(repository.updated_payload.model_name, "small")
        self.assertEqual(repository.updated_payload.device, "cpu")
        self.assertIsNone(repository.updated_payload.api_key)
        self.assertIsNone(repository.updated_payload.base_url)

    def test_local_support_status_reports_faster_whisper_dependency(self):
        service = STTProfileService(repository=FakeRepository())

        with patch("app.services.stt_profile_service.importlib.util.find_spec", return_value=None):
            status = service.get_local_support_status()

        self.assertFalse(status.installed)
        self.assertEqual(status.provider, "faster-whisper")
        self.assertIn("requirements.local-transcribers.txt", status.install_command)

if __name__ == "__main__":
    unittest.main()
