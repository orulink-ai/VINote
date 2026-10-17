from contextlib import contextmanager
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db import Base
from app.models.workspace import PutNote, SharedVersion, now
from app.services import workspace_service, content_plugin_service as module
from app.routers.content_plugins import Preview


@pytest.fixture
def service(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'plugins.db'}")
    Base.metadata.create_all(engine)
    @contextmanager
    def sessions():
        with Session(engine) as db, db.begin(): yield db
    monkeypatch.setattr(module, "session_scope", sessions)
    monkeypatch.setattr(workspace_service, "session_scope", sessions)
    client = module.ContentPluginService()
    client.workspace.put("a", "note", PutNote(base_revision=0, operation_id="initial", title="会议", content="[12:36](#t=756) 已确认负责人为王工。", versions=[SharedVersion(id="v1", title="会议", content="[12:36](#t=756) 已确认负责人为王工。", created_at=now())]))
    client.setting("a", "actions", True)
    calls = []
    class LLM:
        model = "synthetic-test-model"
        def _complete(self, **kwargs):
            calls.append(kwargs)
            return "# Meeting\n[12:36](#t=756) Confirmed owner: Engineer Wang."
    @contextmanager
    def summarize(*args): yield LLM()
    monkeypatch.setattr(module, "summarizer", summarize)
    yield client, calls
    engine.dispose()


def payload(**kwargs):
    return Preview(plugin_id="actions", note_key="note", version_id="v1", base_revision=1, operation_id="one", **kwargs)


def test_cancelled_visualization_cannot_install_or_start(service):
    client, calls = service
    assert all(item["id"] != "diagram" for item in client.catalog("a"))
    with pytest.raises(HTTPException) as installed:
        client.setting("a", "diagram", True)
    assert installed.value.status_code == 409
    request = Preview(plugin_id="diagram", note_key="note", version_id="v1", base_revision=1, operation_id="cancelled-visual")
    with pytest.raises(HTTPException) as started:
        client.start(("a", "local"), request)
    assert started.value.status_code == 409
    assert not calls


def test_remote_visualization_retry_is_blocked_before_outbound_write(monkeypatch):
    from app.routers import content_plugins as routes
    calls = []
    def proxy(identity, method, path, *args):
        calls.append((method, path))
        return True, {"plugin_id": "diagram", "status": "failed"}
    monkeypatch.setattr(routes, "proxy_integration", proxy)
    with pytest.raises(HTTPException) as error:
        routes.retry("existing-run", None, ("a", "local"))
    assert error.value.status_code == 409
    assert calls == [("GET", "/api/plugins/runs/existing-run")]


def test_preview_isolated_and_repeat_does_not_repeat_model_or_save(service):
    client, calls = service
    result = client.start(("a", "local"), payload())
    assert result["status"] == "ready"
    assert client.workspace.get("a", "note")["revision"] == 1
    assert client.start(("a", "local"), payload())["id"] == result["id"]
    assert len(calls) == 1
    assert not client.catalog("b")[0]["installed"]
    with pytest.raises(HTTPException) as error: client.get("b", result["id"])
    assert error.value.status_code == 404
    saved = client.save("a", result["id"])
    assert saved["revision"] == 2
    assert client.save("a", result["id"])["revision"] == 2
    assert any(version["id"] == "v1" for version in saved["versions"])
    assert sum(version["id"].startswith("plugin-") for version in saved["versions"]) == 1


def test_concurrent_edit_preserves_preview_and_new_body(service):
    client, _ = service
    client.start(("a", "local"), payload())
    client.workspace.put("a", "note", PutNote(base_revision=1, operation_id="other-device", title="会议", content="另一个设备的编辑"))
    with pytest.raises(HTTPException) as error: client.save("a", "one")
    assert error.value.status_code == 409
    assert client.get("a", "one")["output"]
    assert client.workspace.get("a", "note")["content"] == "另一个设备的编辑"


def test_lost_save_receipt_reuses_payload_without_duplicate_versions(service, monkeypatch):
    client, _ = service
    client.start(("a", "local"), payload())
    real_put = client.workspace.put
    def lost_receipt(*args, **kwargs):
        real_put(*args, **kwargs)
        raise HTTPException(503, "simulated lost receipt")
    monkeypatch.setattr(client.workspace, "put", lost_receipt)
    with pytest.raises(HTTPException): client.save("a", "one")
    monkeypatch.setattr(client.workspace, "put", real_put)
    assert client.save("a", "one")["revision"] == 2
    assert sum(version["id"].startswith("plugin-") for version in client.workspace.get("a", "note")["versions"]) == 1


def test_failed_generation_requires_explicit_retry_and_keeps_source(service, monkeypatch):
    client, calls = service
    good = module.summarizer
    @contextmanager
    def broken(*args): raise RuntimeError("provider secret must not leak"); yield
    monkeypatch.setattr(module, "summarizer", broken)
    failed = client.start(("a", "local"), payload())
    assert failed["status"] == "failed" and "secret" not in failed["error"]
    assert client.workspace.get("a", "note")["revision"] == 1
    monkeypatch.setattr(module, "summarizer", good)
    assert client.start(("a", "local"), payload())["status"] == "failed"
    assert not calls
    assert client.retry(("a", "local"), "one")["status"] == "ready"
    assert len(calls) == 1


def test_disabled_plugin_and_changed_operation_inputs_are_rejected(service):
    client, _ = service
    client.start(("a", "local"), payload())
    with pytest.raises(HTTPException) as error: client.start(("a", "local"), payload(language="ja"))
    assert error.value.status_code == 409
    client.setting("a", "actions", True, False)
    request = payload(); request.operation_id = "second"
    with pytest.raises(HTTPException) as error: client.start(("a", "local"), request)
    assert error.value.status_code == 409


def test_recovery_includes_fixed_source_version_and_language(service):
    client, _ = service
    first = client.start(("a", "local"), payload(language="zh"))
    client.workspace.put("a", "note", PutNote(base_revision=1, operation_id="later", title="新标题", content="新的当前正文"))
    recovered = client.get("a", first["id"])
    assert recovered["source_version_id"] == "v1"
    assert recovered["language"] == "zh"
    assert recovered["source_content"] == "[12:36](#t=756) 已确认负责人为王工。"
    assert "source_content" not in client.runs("a")[0]


@pytest.mark.parametrize("late_error", [False, True])
def test_expired_attempt_cannot_overwrite_a_newer_attempt(service, monkeypatch, late_error):
    client, _ = service
    from app.models.content_plugins import ContentPluginRunDB

    class StaleLLM:
        model = "old-attempt"

        def _complete(self, **kwargs):
            with module.session_scope() as db:
                row = db.get(ContentPluginRunDB, ("a", "one"))
                row.lease_until += 1
                row.output = "新尝试已经确认的输出"
                row.status = "ready"
                row.model = "new-attempt"
            if late_error:
                raise RuntimeError("old attempt failed after superseded")
            return "旧尝试的迟到输出"

    @contextmanager
    def summarize(*args):
        yield StaleLLM()

    monkeypatch.setattr(module, "summarizer", summarize)
    result = client.start(("a", "local"), payload())
    assert result["status"] == "ready"
    assert result["model"] == "new-attempt"
    assert result["output"] == "新尝试已经确认的输出"


def test_cross_worker_duplicate_insert_runs_model_only_once(service, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    client, calls = service
    barrier = Barrier(2)
    real_version = client.workspace.version

    def version(*args):
        source = real_version(*args)
        barrier.wait(timeout=5)
        return source

    @contextmanager
    def no_process_lock(*args):
        yield

    monkeypatch.setattr(module, "lock", no_process_lock)
    monkeypatch.setattr(client.workspace, "version", version)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.start(("a", "local"), payload()), range(2)))
    assert {row["id"] for row in results} == {"one"}
    assert len(calls) == 1


def test_concurrent_retry_has_one_claim_and_exposes_safe_retry_capability(service, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event
    from app.models.content_plugins import ContentPluginRunDB

    client, _ = service
    client.start(("a", "local"), payload())
    assert not client.get("a", "one")["retry_safe"]
    with module.session_scope() as db:
        row = db.get(ContentPluginRunDB, ("a", "one"))
        row.status = "failed"
    assert client.get("a", "one")["retry_safe"]
    barrier, release = Barrier(2), Event()
    executions = []

    @contextmanager
    def no_process_lock(*args):
        barrier.wait(timeout=5)
        yield

    def execute(identity, run_id, bearer=None, *, lease_token):
        executions.append(lease_token)
        assert release.wait(timeout=5)
        return client.get(identity[0], run_id)

    monkeypatch.setattr(module, "lock", no_process_lock)
    monkeypatch.setattr(client, "execute", execute)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.retry, ("a", "local"), "one") for _ in range(2)]
        from concurrent.futures import wait, FIRST_COMPLETED
        completed, _ = wait(futures, timeout=5, return_when=FIRST_COMPLETED)
        release.set()
        assert completed
        results = [future.result() for future in futures]
    assert len(executions) == 1
    assert all(row["status"] == "running" and not row["retry_safe"] for row in results)


@pytest.mark.parametrize("language", ["zh", "en", "ja", "de", "unknown", None])
def test_builtin_translation_is_blocked_without_relabeling_history(service, language):
    import json
    from app.models.content_plugins import ContentPluginRunDB
    client, calls = service
    request = payload(language=language or "en")
    request.plugin_id = "translation"
    with pytest.raises(HTTPException) as error:
        client.start(("a", "local"), request)
    assert error.value.status_code == 409 and not calls
    assert "translation" not in {item["id"] for item in client.catalog("a")}
    with pytest.raises(HTTPException): client.setting("a", "translation", True)
    client.start(("a", "local"), payload())
    with module.session_scope() as db:
        row = db.get(ContentPluginRunDB, ("a", "one"))
        snapshot = json.loads(row.snapshot)
        if language is None:
            snapshot.pop("language", None)
        else:
            snapshot["language"] = language
        row.snapshot = json.dumps(snapshot)
        row.plugin_id = "translation"
        row.status = "failed"
    recovered = client.get("a", "one")
    assert recovered["language"] == (language or "") and recovered["output"]
    assert not recovered["retry_safe"]
    with pytest.raises(HTTPException) as error:
        client.retry(("a", "local"), "one")
    assert error.value.status_code == 409
    assert len(calls) == 1
