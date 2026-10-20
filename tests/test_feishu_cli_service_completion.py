"""Service-to-CLI completion guards with real transactions, no real CLI."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import subprocess
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.db_models import FeishuConnectionDB
from app.services import feishu_cli as cli
from app.services import feishu_cli_service as module
from app.services.feishu_cli_service import FeishuCLIService, USER
from app.services.feishu_service import FeishuError, _lock


@pytest.fixture
def completion(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("real CLI/network is forbidden")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(settings, "model_profile_encryption_key", "synthetic-test-key")
    monkeypatch.setattr(cli, "_flows", {"synthetic-flow": {
        "owner": "alice", "stage": "authorization", "until": time.time() + 600,
        "generation": "synthetic-generation", "exchange_complete": True,
    }})
    monkeypatch.setattr(cli, "_owner_generations", {"alice": "synthetic-generation"})
    engine = create_engine("sqlite:///" + (tmp_path / "completion.db").as_posix(),
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[FeishuConnectionDB.__table__])
    ctx = SimpleNamespace(service=FeishuCLIService("alice"), calls=[], on_read=lambda: None,
                          before_transaction=lambda: None, after_flush=lambda: None,
                          on_commit=lambda: None)

    @contextmanager
    def scope():
        ctx.before_transaction()
        with Session(engine) as db:
            try:
                yield db
                db.flush()
                ctx.after_flush()
                db.commit()
                ctx.on_commit()
            except BaseException:
                db.rollback()
                raise

    monkeypatch.setattr(module, "session_scope", scope)
    ctx.scope = scope
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    raw = {"appId": "cli_synthetic", "brand": "feishu", "identities": {"user": {
        "openId": "ou_alice", "tokenStatus": "valid", "expiresAt": expiry, "scope": "docs:read"}}}

    def auth_status(owner):
        ctx.calls.append(("status", owner))
        return deepcopy(raw)

    def api(owner, method, path, **kwargs):
        assert (owner, method, path) == ("alice", "GET", "authen/v1/user_info")
        ctx.calls.append(("identity", owner))
        ctx.on_read()
        return {"open_id": "ou_alice", "tenant_key": "synthetic-tenant", "name": "合成用户"}

    monkeypatch.setattr(cli, "auth_status", auth_status)
    monkeypatch.setattr(cli, "api", api)
    yield ctx
    engine.dispose()


@pytest.mark.parametrize("flow_id", [None, "missing-flow"])
def test_connect_requires_original_live_exchanged_flow_before_external_reads(completion, flow_id):
    with pytest.raises(FeishuError):
        completion.service._verify_identity("alice", connect=True, flow_id=flow_id)
    assert not completion.calls


@pytest.mark.parametrize("invalidation", ["cancel", "expire", "new_flow", "wrong_owner"])
def test_late_identity_result_cannot_commit_revoked_flow(completion, invalidation):
    def invalidate():
        if invalidation == "cancel":
            cli.cancel("alice")
        elif invalidation == "expire":
            cli._flows["synthetic-flow"]["until"] = time.time() - 1
        elif invalidation == "new_flow":
            cli._owner_generations["alice"] = "new-generation"
        else:
            cli._flows["synthetic-flow"]["owner"] = "bob"
    completion.on_read = invalidate
    with pytest.raises(FeishuError) as error:
        completion.service._verify_identity("alice", connect=True, flow_id="synthetic-flow")
    assert error.value.code == "authorization_cancelled"
    with completion.scope() as db:
        assert db.get(FeishuConnectionDB, "alice") is None


def test_cancel_in_gap_after_readback_check_is_rechecked_inside_commit_guard(completion):
    @contextmanager
    def owner_lock(owner):
        cli.cancel("alice")
        with _lock(owner):
            yield

    # This is precisely the gap between completion_check and completion_commit.
    from unittest.mock import patch
    with patch.object(module, "_lock", owner_lock), pytest.raises(FeishuError):
        completion.service._verify_identity("alice", connect=True, flow_id="synthetic-flow")
    with completion.scope() as db:
        assert db.get(FeishuConnectionDB, "alice") is None


def test_cancel_after_flush_waits_until_actual_commit_finishes(completion):
    attempted, cancelled = threading.Event(), threading.Event()
    observed, workers = [], []

    def cancel():
        attempted.set()
        cli.cancel("alice")
        cancelled.set()

    def flushed():
        worker = threading.Thread(target=cancel)
        workers.append(worker)
        worker.start()
        assert attempted.wait(2)
        assert not cancelled.wait(.1), "flow guard must cover transaction commit, not only flush"

    completion.after_flush = flushed
    completion.on_commit = lambda: observed.append(cancelled.is_set())
    try:
        completion.service._verify_identity("alice", connect=True, flow_id="synthetic-flow")
    finally:
        for worker in workers:
            worker.join(2)
    completion.after_flush = lambda: None
    completion.on_commit = lambda: None
    assert observed == [False] and cancelled.is_set()
    assert not any(worker.is_alive() for worker in workers)
    with completion.scope() as db:
        assert db.get(FeishuConnectionDB, "alice").open_id == "ou_alice"


def test_success_consumes_flow_only_after_actual_db_commit_and_no_network_in_guard(completion):
    observed = []
    original = cli.completion_check

    def committed():
        # Real db.commit has completed, but the guard has not yet consumed flow.
        original("alice", "synthetic-flow")
        observed.append("committed_inside_live_guard")

    completion.on_commit = committed
    assert completion.service._verify_identity("alice", connect=True, flow_id="synthetic-flow") == USER
    completion.on_commit = lambda: None
    assert observed == ["committed_inside_live_guard"]
    assert "synthetic-flow" not in cli._flows
    with completion.scope() as db:
        row = db.get(FeishuConnectionDB, "alice")
        assert row.open_id == "ou_alice" and not row.expired
        assert json.loads(row.preferences)["connection_id"]
    before = len(completion.calls)
    with pytest.raises(FeishuError):
        completion.service._verify_identity("alice", connect=True, flow_id="synthetic-flow")
    assert len(completion.calls) == before


def test_transaction_failure_rolls_back_and_consumes_flow(completion):
    def fail():
        raise RuntimeError("synthetic transaction failure")
    completion.after_flush = fail
    with pytest.raises(RuntimeError, match="synthetic transaction"):
        completion.service._verify_identity("alice", connect=True, flow_id="synthetic-flow")
    completion.after_flush = lambda: None
    assert "synthetic-flow" not in cli._flows
    with completion.scope() as db:
        assert db.get(FeishuConnectionDB, "alice") is None


def test_network_read_allows_cancellation_instead_of_holding_commit_guard(completion):
    cancelled = threading.Event()
    failures = []

    def cancel():
        try:
            cli.cancel("alice")
            cancelled.set()
        except BaseException as exc:
            failures.append(exc)

    def while_reading():
        worker = threading.Thread(target=cancel)
        worker.start()
        try:
            assert cancelled.wait(2), "network read must not hold the flow commit lock"
        finally:
            worker.join(2)

    completion.on_read = while_reading
    with pytest.raises(FeishuError):
        completion.service._verify_identity("alice", connect=True, flow_id="synthetic-flow")
    assert cancelled.is_set() and not failures
    with completion.scope() as db:
        assert db.get(FeishuConnectionDB, "alice") is None


def test_complete_route_cannot_recreate_connection_after_late_cancel(completion, monkeypatch):
    monkeypatch.setattr(cli, "complete", lambda owner, flow: None)
    completion.on_read = lambda: cli.cancel("alice")
    with pytest.raises(FeishuError) as error:
        completion.service.complete_authorization("alice", "synthetic-flow")
    assert error.value.code == "authorization_cancelled"
    with completion.scope() as db:
        assert db.get(FeishuConnectionDB, "alice") is None


def test_service_owner_mismatch_stops_before_identity_readback(completion):
    with pytest.raises(FeishuError) as error:
        completion.service._verify_identity("bob", connect=True, flow_id="synthetic-flow")
    assert error.value.code == "connection_changed"
    assert completion.calls == []


def test_complete_authorization_passes_original_flow_and_pending_stage_never_saves(completion, monkeypatch):
    observed = []
    pending = {"flow_id": "synthetic-flow", "stage": "application", "pending": True}
    monkeypatch.setattr(cli, "complete", lambda owner, flow: pending)
    monkeypatch.setattr(completion.service, "_verify_identity",
        lambda owner, **kwargs: observed.append((owner, kwargs)))
    monkeypatch.setattr(completion.service, "status", lambda owner: {"connected": True})
    assert completion.service.complete_authorization("alice", "synthetic-flow") == pending
    assert observed == []
    monkeypatch.setattr(cli, "complete", lambda owner, flow: None)
    assert completion.service.complete_authorization("alice", "synthetic-flow") == {"connected": True}
    assert observed == [("alice", {"connect": True, "flow_id": "synthetic-flow"})]


def test_completion_cannot_switch_cli_profile_before_frozen_dispatch_finishes(completion, monkeypatch):
    from app.services import feishu_auto_policy as policy, feishu_service as base
    from app.services.cloud_account_service import _cipher
    from contextvars import copy_context

    ctx = completion
    monkeypatch.setattr(base, "session_scope", ctx.scope)
    with ctx.scope() as db:
        db.add(FeishuConnectionDB(owner="alice", open_id="ou_alice",
            tokens=_cipher().encrypt(json.dumps({"transport": "cli", "app_id": "cli_synthetic",
                "tenant_key": "synthetic-tenant", "scope": "docs:read"}).encode()).decode(),
            preferences=json.dumps({"connection_id": "original-connection"})))
    flow = cli._flows["synthetic-flow"]
    flow.pop("exchange_complete")
    flow.update(code="synthetic-code", busy=False)
    profile = {"open_id": "ou_alice"}
    dispatching, release, boundary, exchanged = (threading.Event() for _ in range(4))
    sent_as, outcomes = [], []
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    def status(owner):
        return {"appId": "cli_synthetic", "brand": "feishu", "identities": {"user": {
            "openId": profile["open_id"], "tokenStatus": "valid", "expiresAt": expiry, "scope": "docs:read"}}}

    def exchange(owner, args, **kwargs):
        assert args[:2] == ["auth", "login"]
        profile["open_id"] = "ou_reconnected"
        exchanged.set()
        boundary.set()
        return {"ok": True}

    def api(owner, method, path, **kwargs):
        if method == "GET":
            assert path == "authen/v1/user_info"
            return {"open_id": profile["open_id"], "tenant_key": "synthetic-tenant", "name": "合成用户"}
        assert (method, path) == ("POST", "docx/v1/documents")
        dispatching.set()
        assert release.wait(3)
        # Model the child CLI resolving its config on process startup, after
        # the service snapshot check. This is the previously unguarded gap.
        sent_as.append(profile["open_id"])
        return {"document": {"document_id": "synthetic-doc"}}

    def owner_lock(owner):
        if threading.current_thread().name == "synthetic-reconnect":
            boundary.set()
        return _lock(owner)

    monkeypatch.setattr(cli, "auth_status", status)
    monkeypatch.setattr(cli, "api", api)
    monkeypatch.setattr(cli, "run", exchange)
    monkeypatch.setattr(module, "_lock", owner_lock)
    snapshot = {"open_id": "ou_alice", "app_id": "cli_synthetic", "tenant_key": "synthetic-tenant",
                "connection_id": "original-connection", "contact_selection_protocol": 1}
    marker = policy.active_delivery.set(("alice", snapshot))
    try:
        context = copy_context()
    finally:
        policy.active_delivery.reset(marker)

    def write():
        try:
            ctx.service.request("POST", "docx/v1/documents", token=USER, body={"title": "合成纪要"})
            outcomes.append("written")
        except BaseException as error:
            outcomes.append(error)

    def reconnect():
        try:
            ctx.service.complete_authorization("alice", "synthetic-flow")
        except FeishuError as error:
            outcomes.append(error.code)

    writer = threading.Thread(target=context.run, args=(write,), name="synthetic-dispatch")
    completer = threading.Thread(target=reconnect, name="synthetic-reconnect")
    writer.start()
    try:
        assert dispatching.wait(3)
        completer.start()
        assert boundary.wait(3)
        switched_during_dispatch = exchanged.is_set()
    finally:
        release.set()
        writer.join(3)
        if completer.ident is not None:
            completer.join(3)
    assert not writer.is_alive() and not completer.is_alive()
    assert sent_as == ["ou_alice"], "a frozen original delivery must not use the exchanged CLI profile"
    assert switched_during_dispatch is False
    assert outcomes == ["written", "connection_changed"]


@pytest.mark.parametrize("window", ["exchange", "identity_readback"])
def test_owner_execution_lock_does_not_block_flow_cancel_during_completion(completion, monkeypatch, window):
    ctx = completion
    flow = cli._flows["synthetic-flow"]
    flow.pop("exchange_complete")
    flow.update(code="synthetic-code", busy=False)
    entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
    errors = []

    def exchange(*args, **kwargs):
        if window == "exchange":
            entered.set()
            assert release.wait(3)
        return {"ok": True}

    def readback():
        if window == "identity_readback":
            entered.set()
            assert release.wait(3)

    def complete():
        try:
            ctx.service.complete_authorization("alice", "synthetic-flow")
        except FeishuError as error:
            errors.append(error.code)

    def cancel():
        cli.cancel("alice")
        cancelled.set()

    ctx.on_read = readback
    monkeypatch.setattr(cli, "run", exchange)
    worker, canceller = threading.Thread(target=complete), threading.Thread(target=cancel)
    worker.start()
    try:
        assert entered.wait(3)
        canceller.start()
        assert cancelled.wait(3), "owner execution lock must not hold the flow epoch lock during network I/O"
    finally:
        release.set()
        worker.join(3)
        if canceller.ident is not None:
            canceller.join(3)
    assert not worker.is_alive() and not canceller.is_alive()
    assert errors == ["authorization_cancelled"]
    with ctx.scope() as db:
        assert db.get(FeishuConnectionDB, "alice") is None
