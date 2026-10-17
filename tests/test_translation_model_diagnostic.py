"""Credential-free whitelist tests; no real account, network or model calls."""
import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("model_diagnostic",
    Path(__file__).resolve().parents[1] / "scripts/check_translation_model_metadata.py")
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


def test_response_whitelist_does_not_echo_secrets_or_owner_email():
    token, email = "sensitive-session-value", "owner@example.test"
    raw = {"data": [{"id": "chosen", "modelType": "llm", "runtimeStatus": "available",
                     "api_key": token, "description": email},
                    {"id": token, "modelType": "llm", "runtimeStatus": "available"}],
           "llm_model": token, "credential": token, "error": {"message": email}}
    result = diagnostic.metadata(raw, token=token, email=email)
    encoded = json.dumps(result)
    assert token not in encoded and email not in encoded and "credential" not in encoded
    assert result["models"][0] == {"id": "chosen", "modelType": "llm", "runtimeStatus": "available"}
    assert result["llm_model"] == result["models"][1]["id"] == "[omitted]"


def test_diagnostics_send_current_session_only_to_two_fixed_gets():
    requests = []

    class Client:
        @contextmanager
        def stream(self, method, url, headers):
            requests.append((method, url, headers))
            raw = {"llm_model": "default"} if url.endswith("default-models") else {
                "data": [{"id": "chosen", "modelType": "llm", "runtimeStatus": "available"}]}
            yield SimpleNamespace(status_code=200, headers={}, iter_raw=lambda: [json.dumps(raw).encode()])

    results = diagnostic.collect(Client(), "memory-only-session", "owner@example.test")
    assert [r[0] for r in requests] == ["GET", "GET"]
    assert [r[1] for r in requests] == [diagnostic.ORIGIN + path for path in diagnostic.PATHS]
    assert all(r[2]["Authorization"] == "Bearer memory-only-session" for r in requests)
    assert "memory-only-session" not in json.dumps(results)
    assert results[0]["models"][0]["id"] == "chosen" and results[1]["llm_model"] == "default"


def test_errors_do_not_print_body_or_exception_details():
    class Client:
        @contextmanager
        def stream(self, *args, **kwargs):
            raise RuntimeError("secret body and bearer credential")
            yield
    encoded = json.dumps(diagnostic.collect(Client(), "session", "owner@example.test"))
    assert "secret body" not in encoded and "credential" not in encoded
    assert encoded.count("metadata_unavailable") == 2


def test_http_rejection_does_not_read_untrusted_body():
    class Client:
        @contextmanager
        def stream(self, *args, **kwargs):
            def forbidden(): raise AssertionError("Must not read error body")
            yield SimpleNamespace(status_code=401, headers={}, iter_raw=forbidden)
    results = diagnostic.collect(Client(), "session", "owner@example.test")
    assert all(result["http"] == 401 and "error" not in result for result in results)


def test_selected_model_lookup_is_not_limited_by_display_page():
    rows = [{"id": f"model-{index}", "modelType": "llm", "runtimeStatus": "available"} for index in range(120)]
    result = diagnostic.metadata({"data": rows}, selected="model-119")
    assert len(result["models"]) == 100
    assert result["selected_model_status"] == [{"id": "model-119", "modelType": "llm", "runtimeStatus": "available"}]
