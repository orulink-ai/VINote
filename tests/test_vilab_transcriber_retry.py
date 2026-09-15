from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.models.transcript import TranscriptResult
from app.transcribers.vilab_transcriber import VILabTranscriber


def test_transient_gateway_failure_retries_same_normalized_audio():
    adapter = VILabTranscriber("http://localhost", "test")
    expected = TranscriptResult(None, "测试", [])
    with patch("app.transcribers.vilab_transcriber.subprocess.run"), patch(
        "app.transcribers.vilab_transcriber.time.sleep"
    ), patch.object(adapter, "_transcribe_normalized", side_effect=[
        HTTPException(502, "云端模型请求失败（HTTP 502）"), expected
    ]) as request:
        assert adapter.transcribe("sample.wav") is expected
        assert request.call_count == 2
        assert request.call_args_list[0] == request.call_args_list[1]


@pytest.mark.parametrize("detail,count", [
    ("云端模型请求失败（HTTP 503）", 3),
    ("云端服务未接受当前身份", 1),
])
def test_retries_are_bounded_and_do_not_hide_authentication_failure(detail, count):
    adapter = VILabTranscriber("http://localhost", "test")
    with patch("app.transcribers.vilab_transcriber.subprocess.run"), patch(
        "app.transcribers.vilab_transcriber.time.sleep"
    ), patch.object(adapter, "_transcribe_normalized", side_effect=HTTPException(502, detail)) as request:
        with pytest.raises(HTTPException):
            adapter.transcribe("sample.wav")
        assert request.call_count == count
