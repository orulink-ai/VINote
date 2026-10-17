import logging
import time

import httpx
from fastapi import HTTPException

from app.config import settings
from app.llm.anthropic_compat import post_anthropic_compatible
from app.models.model_profile import ModelProfileTestRequest, ModelProfileTestResponse

logger = logging.getLogger(__name__)

OPENAI_COMPATIBLE_TEST_TEMPERATURE = 0.7
OPENAI_COMPATIBLE_TEST_MESSAGES = [
    {"role": "system", "content": "You are a concise connection test assistant."},
    {"role": "user", "content": "ping"},
]


class ModelProfileConnectionService:
    @staticmethod
    def _build_openai_url(base_url: str) -> str:
        base = base_url.rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    @staticmethod
    def _build_anthropic_url(base_url: str) -> str:
        base = base_url.rstrip("/")
        if base.endswith("/v1/messages"):
            return base
        if base.endswith("/messages"):
            return base
        if base.endswith("/v1"):
            return f"{base}/messages"
        return f"{base}/v1/messages"

    @staticmethod
    def _build_azure_url(base_url: str, model_name: str) -> str:
        base = base_url.rstrip("/")
        if "chat/completions" in base:
            if "api-version=" in base:
                return base
            separator = "&" if "?" in base else "?"
            return f"{base}{separator}api-version={settings.azure_openai_api_version}"
        return (
            f"{base}/openai/deployments/{model_name}"
            f"/chat/completions?api-version={settings.azure_openai_api_version}"
        )

    def test_connection(self, payload: ModelProfileTestRequest) -> ModelProfileTestResponse:
        start = time.perf_counter()
        ok = False
        error_message = ""

        try:
            if payload.provider in {"openai-compatible", "groq-openai-compatible", "ollama"}:
                headers = {"Content-Type": "application/json"}
                if payload.provider != "ollama":
                    headers["Authorization"] = f"Bearer {payload.api_key}"
                response = httpx.post(
                    self._build_openai_url(payload.base_url),
                    headers=headers,
                    json={
                        "model": payload.model_name,
                        "messages": OPENAI_COMPATIBLE_TEST_MESSAGES,
                        "max_tokens": 1,
                        "temperature": OPENAI_COMPATIBLE_TEST_TEMPERATURE,
                    },
                    timeout=20.0,
                )
                response.raise_for_status()
                ok = True
            elif payload.provider == "anthropic-compatible":
                response = post_anthropic_compatible(
                    url=self._build_anthropic_url(payload.base_url),
                    api_key=payload.api_key,
                    json_body={
                        "model": payload.model_name,
                        "messages": [{"role": "user", "content": [{"type": "text", "text": "ping"}]}],
                        "max_tokens": 1,
                    },
                    timeout=20.0,
                )
                ok = True
            elif payload.provider == "azure-openai":
                response = httpx.post(
                    self._build_azure_url(payload.base_url, payload.model_name),
                    headers={
                        "Content-Type": "application/json",
                        "api-key": payload.api_key,
                    },
                    json={
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                    timeout=20.0,
                )
                response.raise_for_status()
                ok = True
            else:
                raise HTTPException(status_code=400, detail="Unsupported provider")
        except HTTPException as exc:
            error_message = str(exc.detail)
        except httpx.HTTPStatusError as exc:
            error_message = exc.response.text or f"HTTP {exc.response.status_code}"
        except Exception as exc:
            logger.warning("Model profile connection test failed", exc_info=True)
            error_message = str(exc)

        return ModelProfileTestResponse(
            ok=ok,
            provider=payload.provider,
            model=payload.model_name,
            latency_ms=int((time.perf_counter() - start) * 1000),
            error_message=error_message,
        )
