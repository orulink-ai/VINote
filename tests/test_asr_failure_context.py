"""Failure persistence only: no provider, model, auth or tracing network calls."""
import json
import socket
from unittest.mock import patch

import pytest

from app.services.asr_stream_service import ASRServiceError
from app.services.task_artifact_service import TaskArtifactService
from app.services.task_failure import failure_details, safe_asr_failure_context
from app.transcribers.vilab_transcriber import VILabTranscriber


SESSION = "9dbfb390-fe2c-433a-aa11-3eae0e08bd9e"
SENSITIVE = "SYNTHETIC_SECRET_AND_TRANSCRIPT_MUST_NOT_PERSIST"


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("offline diagnostic test forbids network")
    monkeypatch.setattr(socket.socket, "connect", denied)


def failed_error():
    error = ASRServiceError("asr_provider_error", session_id=SESSION, stage="asr", sent_all=False)
    error.asr_metadata = {"model": SENSITIVE, "asr_attempts": [{
        "model": SENSITIVE, "attempt": 1, "status": "failed",
        "reason": "non_retryable", "diagnostic": error.diagnostic,
    }]}
    return error


def test_real_adapter_failure_reaches_atomic_status_without_retry_or_model_call(tmp_path):
    adapter = VILabTranscriber("https://example.invalid", SENSITIVE, model="frozen-model")
    error = ASRServiceError("asr_provider_error", session_id=SESSION, stage="asr", sent_all=False)
    with patch("app.transcribers.vilab_transcriber.subprocess.run"), patch.object(
        adapter, "_transcribe_normalized", side_effect=error
    ) as call, patch("app.transcribers.vilab_transcriber.time.sleep") as sleep:
        with pytest.raises(ASRServiceError) as caught:
            adapter.transcribe("synthetic.wav")
    call.assert_called_once()
    sleep.assert_not_called()
    assert adapter.model == "frozen-model"
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir("offline-task")
    artifacts.update_status(folder, "transcribing", received_seconds=745.6,
                            processed_seconds=0, total_seconds=1376.549)
    artifacts.update_status(folder, "failed", failed_stage="transcribing",
                            **failure_details(caught.value))
    saved = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    assert saved["error_code"] == "asr_provider_error" and saved["retryable"] is False
    context = saved["asr_failure_context"]
    assert context["task_attempt"] == 1
    assert context["diagnostic"] == {"code": "asr_provider_error", "session_id": SESSION,
                                     "stage": "asr", "sent_all": False}
    assert context["asr_attempts"][0]["attempt"] == 1
    assert context["asr_attempts"][0]["reason"] == "non_retryable"
    assert saved["received_seconds"] == 745.6
    assert "provider_code" not in json.dumps(context)  # Not supplied by the wire protocol.
    assert SENSITIVE not in json.dumps(saved)


def test_projection_drops_raw_messages_auth_model_and_untransported_provider_fields():
    error = failed_error()
    raw = {"schema_version": 1, "message": SENSITIVE, "authorization": SENSITIVE,
           "diagnostic": {**error.diagnostic, "provider_code": 55000000, "body": SENSITIVE},
           "asr_attempts": [{"attempt": n, "status": "failed", "reason": SENSITIVE,
                             "diagnostic": {**error.diagnostic, "body": SENSITIVE},
                             "model": SENSITIVE} for n in range(1, 101)]}
    context = safe_asr_failure_context(raw)
    assert len(context["asr_attempts"]) == 3
    assert SENSITIVE not in json.dumps(context)
    assert "provider_code" not in json.dumps(context)
    assert all("reason" not in attempt for attempt in context["asr_attempts"])


def test_outer_failed_write_preserves_context_and_parallel_callback_cannot_erase_it(tmp_path):
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir("offline-task")
    artifacts.update_status(folder, "failed", **failure_details(failed_error()))
    before = artifacts.get_status("offline-task")["asr_failure_context"]
    artifacts.update_status(folder, "failed", "outer generic failure", retryable=True)
    artifacts.update_status(folder, "transcribing", speaker_analysis_ready=True)
    saved = artifacts.get_status("offline-task")
    assert saved["asr_failure_context"] == before
    assert saved["retryable"] is False and saved["status"] == "failed"


@pytest.mark.parametrize("stage", ["uploaded", "preparing", "downloading"])
def test_explicit_new_attempt_clears_old_context(stage, tmp_path):
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir("offline-task")
    artifacts.update_status(folder, "failed", **failure_details(failed_error()))
    artifacts.update_status(folder, stage, attempt=2)
    assert "asr_failure_context" not in artifacts.get_status("offline-task")
    artifacts.update_status(folder, "failed", "new unrelated failure")
    assert "asr_failure_context" not in artifacts.get_status("offline-task")


def test_unknown_and_bare_errors_do_not_fabricate_attempts_or_change_retry_policy():
    assert failure_details(RuntimeError(SENSITIVE)) == {}
    assert failure_details(ASRServiceError("service_unavailable")) == {
        "error_code": "service_unavailable", "retryable": True}
    error = ASRServiceError("asr_timeout", session_id=SESSION, stage="asr", sent_all=True)
    details = failure_details(error)
    assert details["error_code"] == "unknown_result" and details["retryable"] is False
    assert details["asr_failure_context"]["asr_attempts"] == []
    assert details["asr_failure_context"]["diagnostic"]["code"] == "asr_timeout"


def test_invalid_types_and_unknown_values_are_not_serialized():
    context = safe_asr_failure_context({"schema_version": 1,
        "diagnostic": {"code": SENSITIVE, "session_id": SENSITIVE, "stage": {}, "sent_all": 1},
        "asr_attempts": [{"attempt": True}, {"attempt": -1}, {"attempt": 1, "status": {}, "reason": []}]})
    assert context == {"schema_version": 1, "diagnostic": {}, "asr_attempts": [{"attempt": 1}]}


def test_context_is_private_failed_artifact_only(tmp_path):
    artifacts = TaskArtifactService(tmp_path)
    folder = artifacts.create_task_dir("offline-task")
    details = failure_details(failed_error())
    artifacts.update_status(folder, "success", asr_failure_context=details["asr_failure_context"])
    assert "asr_failure_context" not in artifacts.get_status("offline-task")
