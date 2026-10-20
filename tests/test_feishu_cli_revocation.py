"""Offline unknown-write and cancelled authorization counterexamples."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import sqlite3
import threading
import time

import httpx
import pytest

from app.config import settings
from app.services import feishu_cli as cli
from app.services.feishu_service import FeishuError


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "desktop_runtime", True)
    monkeypatch.setattr(settings, "workspace_cloud_runtime", False)
    monkeypatch.setattr(settings, "content_cloud_runtime", False)
    monkeypatch.setattr(settings, "feishu_transport", "cli")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(cli, "_flows", {})
    # Reset the new revocation namespace too, once the implementation exists.
    monkeypatch.setattr(cli, "_owner_generations", {}, raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("real CLI and network are forbidden")

    monkeypatch.setattr(cli.subprocess, "run", forbidden)
    monkeypatch.setattr(cli.subprocess, "Popen", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)


def pending(owner="alice", identifier="synthetic-flow"):
    flow = {"owner": owner, "stage": "authorization", "until": time.time() + 100,
            "code": "synthetic-opaque-code", "busy": False}
    cli._flows[identifier] = flow
    return flow


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("identity", ["bot", None, "unexpected"])
def test_response_identity_mismatch_preserves_unknown_write(monkeypatch, method, identity):
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": True, "identity": identity, "data": {"document_id": "synthetic-written"}}

    monkeypatch.setattr(cli, "run", run)
    with pytest.raises(FeishuError) as error:
        cli.api("alice", method, "docx/v1/documents", body={"title": "Synthetic"})
    assert error.value.uncertain is True and error.value.code == "connection_changed"
    assert len(calls) == 1


def test_read_identity_mismatch_stays_known_rejection(monkeypatch):
    monkeypatch.setattr(cli, "run", lambda *a, **k: {"ok": True, "identity": "bot", "data": {}})
    with pytest.raises(FeishuError) as error:
        cli.api("alice", "GET", "authen/v1/user_info")
    assert error.value.code == "connection_changed" and error.value.uncertain is False


def test_cancel_during_exchange_cannot_return_late_success(monkeypatch):
    pending()
    entered, release = threading.Event(), threading.Event()
    calls = []

    def exchange(*args, **kwargs):
        calls.append(args)
        entered.set()
        assert release.wait(2)
        return {"ok": True}

    monkeypatch.setattr(cli, "run", exchange)
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(cli.complete, "alice", "synthetic-flow")
        try:
            assert entered.wait(2)
            cli.cancel("alice")
        finally:
            release.set()
        with pytest.raises(FeishuError) as error:
            result.result(timeout=2)
    assert error.value.code == "authorization_cancelled"
    assert len(calls) == 1 and not cli._flows


def test_successful_exchange_is_one_shot_until_guarded_commit(monkeypatch):
    pending()
    calls = []
    monkeypatch.setattr(cli, "run", lambda *a, **k: calls.append(a) or {"ok": True})
    assert cli.complete("alice", "synthetic-flow") is None
    cli.completion_check("alice", "synthetic-flow")
    with pytest.raises(FeishuError):
        cli.complete("alice", "synthetic-flow")
    assert len(calls) == 1
    committed = []
    with cli.completion_commit("alice", "synthetic-flow"):
        committed.append("synthetic DB commit")
    assert committed and "synthetic-flow" not in cli._flows
    with pytest.raises(FeishuError):
        with cli.completion_commit("alice", "synthetic-flow"):
            pytest.fail("must never commit twice")


def test_cancel_after_exchange_before_identity_readback_blocks_commit(monkeypatch):
    pending()
    monkeypatch.setattr(cli, "run", lambda *a, **k: {"ok": True})
    cli.complete("alice", "synthetic-flow")
    cli.cancel("alice")
    with pytest.raises(FeishuError):
        cli.completion_check("alice", "synthetic-flow")
    with pytest.raises(FeishuError):
        with cli.completion_commit("alice", "synthetic-flow"):
            pytest.fail("cancelled completion must not recreate a connection")


def test_cancel_during_service_readback_cannot_recreate_connection(monkeypatch):
    pending()
    monkeypatch.setattr(cli, "run", lambda *a, **k: {"ok": True})
    cli.complete("alice", "synthetic-flow")
    reading, release = threading.Event(), threading.Event()
    connections = {}

    def service_readback_then_save():
        cli.completion_check("alice", "synthetic-flow")
        reading.set()
        assert release.wait(2)
        with cli.completion_commit("alice", "synthetic-flow"):
            connections["alice"] = "synthetic verified identity"

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(service_readback_then_save)
        try:
            assert reading.wait(2)
            cli.cancel("alice")
        finally:
            release.set()
        with pytest.raises(FeishuError):
            result.result(timeout=2)
    assert connections == {}


def test_commit_guard_serializes_cancel_through_db_commit(monkeypatch, tmp_path):
    pending()
    monkeypatch.setattr(cli, "run", lambda *a, **k: {"ok": True})
    cli.complete("alice", "synthetic-flow")
    committing, release, cancel_started = threading.Event(), threading.Event(), threading.Event()
    database = tmp_path / "synthetic-connections.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE connections (owner TEXT PRIMARY KEY)")
    events = []

    def commit():
        with cli.completion_commit("alice", "synthetic-flow"):
            # The real transaction's __exit__ commits before the guard exits.
            with sqlite3.connect(database) as db:
                db.execute("INSERT INTO connections VALUES (?)", ("alice",))
                committing.set()
                assert release.wait(2)
            events.append("committed")

    def disconnect():
        cancel_started.set()
        cli.cancel("alice")
        with sqlite3.connect(database) as db:
            db.execute("DELETE FROM connections WHERE owner = ?", ("alice",))
        events.append("disconnected")

    with ThreadPoolExecutor(max_workers=2) as executor:
        save = executor.submit(commit)
        cancel = None
        try:
            assert committing.wait(2)
            cancel = executor.submit(disconnect)
            assert cancel_started.wait(2)
            assert not cancel.done()
        finally:
            release.set()
        save.result(timeout=2)
        assert cancel is not None
        cancel.result(timeout=2)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM connections").fetchone()[0] == 0
    assert events == ["committed", "disconnected"]


def test_owner_switch_or_replaced_flow_cannot_reuse_guard(monkeypatch):
    original = pending()
    monkeypatch.setattr(cli, "run", lambda *a, **k: {"ok": True})
    cli.complete("alice", "synthetic-flow")
    with pytest.raises(FeishuError):
        cli.completion_check("bob", "synthetic-flow")
    cli.cancel("alice")
    # Even reintroducing the old flow bytes cannot restore its revoked epoch.
    cli._flows["synthetic-flow"] = deepcopy(original)
    with pytest.raises(FeishuError):
        cli.completion_check("alice", "synthetic-flow")


def test_expired_exchange_during_provider_call_fails_closed(monkeypatch):
    flow = pending()

    def exchange(*args, **kwargs):
        flow["until"] = time.time() - 1
        return {"ok": True}

    monkeypatch.setattr(cli, "run", exchange)
    with pytest.raises(FeishuError):
        cli.complete("alice", "synthetic-flow")
    with pytest.raises(FeishuError):
        cli.completion_check("alice", "synthetic-flow")


def test_failed_db_transaction_consumes_exchange_without_replay(monkeypatch):
    pending()
    calls = []
    monkeypatch.setattr(cli, "run", lambda *a, **k: calls.append(a) or {"ok": True})
    cli.complete("alice", "synthetic-flow")
    with pytest.raises(RuntimeError):
        with cli.completion_commit("alice", "synthetic-flow"):
            raise RuntimeError("synthetic rollback")
    with pytest.raises(FeishuError):
        cli.complete("alice", "synthetic-flow")
    assert len(calls) == 1


def test_shutdown_revokes_exchange_waiting_for_final_save(monkeypatch):
    pending()
    monkeypatch.setattr(cli, "run", lambda *a, **k: {"ok": True})
    cli.complete("alice", "synthetic-flow")
    cli.shutdown()
    with pytest.raises(FeishuError):
        cli.completion_check("alice", "synthetic-flow")


def test_cancel_another_owner_does_not_revoke_current_completion(monkeypatch):
    pending()
    monkeypatch.setattr(cli, "run", lambda *a, **k: {"ok": True})
    cli.complete("alice", "synthetic-flow")
    cli.cancel("bob")
    cli.completion_check("alice", "synthetic-flow")
    with cli.completion_commit("alice", "synthetic-flow"):
        pass


def test_old_exchange_cleanup_cannot_remove_replacement_flow(monkeypatch):
    old = pending()
    replacement = {}

    def exchange(*args, **kwargs):
        cli.cancel("alice")
        replacement.update(owner="alice", stage="authorization", until=time.time() + 100,
                           code="new-synthetic-code", busy=False,
                           generation=cli._owner_generations["alice"])
        cli._flows["synthetic-flow"] = replacement
        return {"ok": True}

    monkeypatch.setattr(cli, "run", exchange)
    with pytest.raises(FeishuError):
        cli.complete("alice", "synthetic-flow")
    assert old["revoked"] is True and cli._flows["synthetic-flow"] is replacement
    assert replacement["code"] == "new-synthetic-code" and not replacement.get("revoked")


def test_duplicate_complete_while_exchange_running_never_calls_provider_twice(monkeypatch):
    pending()
    entered, release = threading.Event(), threading.Event()
    calls = []

    def exchange(*args, **kwargs):
        calls.append(args)
        entered.set()
        assert release.wait(2)
        return {"ok": True}

    monkeypatch.setattr(cli, "run", exchange)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(cli.complete, "alice", "synthetic-flow")
        try:
            assert entered.wait(2)
            with pytest.raises(FeishuError):
                cli.complete("alice", "synthetic-flow")
        finally:
            release.set()
        assert first.result(timeout=2) is None
    assert len(calls) == 1
    with cli.completion_commit("alice", "synthetic-flow"):
        pass
