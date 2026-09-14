from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from app.config import settings
from app.models.transcript import NoSpeechDetectedError
from app.services.vilab_cloud_service import VILabCloudService


@pytest.mark.parametrize("message,exception", [
    ("Aliyun ASR returned an empty transcript.", NoSpeechDetectedError),
    ("ASR upstream unavailable", HTTPException),
])
def test_only_explicit_empty_recognition_is_distinguished(message, exception):
    response = httpx.Response(502, json={"error": {"message": message}})
    with patch.object(settings, "cloud_auth_url", ""), patch.object(
        settings, "vilab_server_url", "http://localhost"
    ), patch("app.services.vilab_cloud_service.httpx.request", return_value=response):
        with pytest.raises(exception):
            VILabCloudService().request(None, "POST", "/v1/asr/transcriptions")
