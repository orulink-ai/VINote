"""v1.0.60 contact shortcut -> partial object selector, entirely offline.

Pinned official contract: larksuite/cli@1dd0758,
shortcuts/contact/contact_search_user.go: searchUserResponse/projectUsers.
"""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
import subprocess

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base
from app.models.auth import AuthenticatedUser
from app.models.feishu_object_hotwords import FeishuObjectAliasDB, FeishuObjectDB
from app.services import feishu_cli as cli, feishu_object_hotwords as hotwords
from app.services.feishu_cli_service import FeishuCLIService, USER
from app.services.feishu_service import FeishuError, FeishuService


BINDING = {"owner": "alice", "connection_id": "synthetic-connection", "sender_open_id": "ou_sender",
           "app_id": "cli_synthetic", "tenant_key": "synthetic-tenant"}
ARGS = ["contact", "+search-user", "--has-chatted", "--exclude-external-users",
        "--page-size", "30", "--as", "user", "--json"]


def page(users=None, has_more=True):
    return {"ok": True, "identity": "user", "data": {
        "users": users if users is not None else [
            {"open_id": "ou_alpha", "localized_name": "合成成员甲", "has_chatted": True,
             "is_cross_tenant": False, "email": "private@example.invalid", "signature": "omit"}],
        "has_more": has_more,
    }}


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("real network, CLI and external writes are forbidden")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(settings, "desktop_runtime", True)
    monkeypatch.setattr(settings, "content_cloud_runtime", False)
    monkeypatch.setattr(settings, "workspace_cloud_runtime", False)
    monkeypatch.setattr(settings, "feishu_transport", "cli")
    engine = create_engine("sqlite:///" + (tmp_path / "catalog.db").as_posix(),
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[FeishuObjectDB.__table__, FeishuObjectAliasDB.__table__])
    sessions = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def scope():
        with sessions.begin() as db:
            yield db

    ctx = SimpleNamespace(binding=deepcopy(BINDING), response=page(), calls=[], events=[])
    cache = hotwords.FeishuObjectHotwordsService(binding_provider=lambda owner: ctx.binding,
                                                cli_enabled=lambda: True, session_factory=scope)
    monkeypatch.setattr(hotwords, "service", cache)
    service = FeishuCLIService("alice")
    monkeypatch.setattr(FeishuService, "for_owner", lambda self, owner: service)

    def verify(owner):
        assert owner == "alice"
        ctx.events.append("verify_identity")
        return USER

    def binding(owner):
        ctx.events.append("binding")
        return deepcopy(ctx.binding)

    def run(owner, args, **kwargs):
        assert owner == "alice" and args == ARGS
        assert kwargs == {"credential_identity": {"app_id": "cli_synthetic", "open_id": "ou_sender"}}
        ctx.calls.append((owner, args.copy()))
        ctx.events.append("contacts_read")
        return deepcopy(ctx.response)

    def request(method, path, **kwargs):
        assert method == "GET" and path == "im/v1/chats" and kwargs["token"] == USER
        ctx.events.append("groups_read")
        return {"items": [{"chat_id": "oc_project", "name": "合成项目群"}], "has_more": False}

    monkeypatch.setattr(service, "user_token", verify)
    monkeypatch.setattr(service, "contact_binding", binding)
    monkeypatch.setattr(service, "request", request)
    monkeypatch.setattr(cli, "run", run)
    ctx.service, ctx.cache = service, cache
    yield ctx
    engine.dispose()


def test_first_refresh_populates_real_shortcut_contacts_and_groups(catalog):
    ctx = catalog
    result = ctx.service.refresh_objects("alice")
    assert result["partial"] is True and result["has_more"] is True
    assert len(ctx.calls) == 1 and ctx.events.index("binding") < ctx.events.index("contacts_read")
    objects = ctx.cache.snapshot("alice", BINDING)["objects"]
    assert {item["id"] for item in objects} == {"ou_alpha", "oc_project"}
    assert next(item for item in objects if item["id"] == "ou_alpha") == {
        "id": "ou_alpha", "name": "合成成员甲", "kind": "contact"}
    assert "email" not in repr(objects) and "signature" not in repr(objects)


@pytest.mark.parametrize("has_more", [True, False])
def test_page_limit_and_partial_are_honest_even_for_empty_valid_page(catalog, has_more):
    ctx = catalog
    ctx.response = page([], has_more)
    result = ctx.service.refresh_objects("alice")
    assert result["has_more"] is has_more and result["partial"] is True
    assert len(ctx.calls) == 1
    assert ctx.cache.snapshot("alice", BINDING)["objects"] == [
        {"id": "oc_project", "name": "合成项目群", "kind": "group"}]


def test_same_names_are_distinct_and_existing_search_contacts_are_retained(catalog):
    ctx = catalog
    ctx.cache.record_objects("alice", BINDING, [{"id": "ou_previous", "name": "先前搜索成员", "kind": "contact"}])
    one = ctx.response["data"]["users"][0]
    ctx.response["data"]["users"] = [one, {**one, "open_id": "ou_beta"}, one]
    ctx.service.refresh_objects("alice")
    assert {item["id"] for item in ctx.cache.snapshot("alice", BINDING)["objects"]} == {
        "ou_previous", "ou_alpha", "ou_beta", "oc_project"}
    assert len(ctx.cache.resolve("alice", BINDING, "合成成员甲")) == 2


@pytest.mark.parametrize("status,code", [(403, "user_scope_missing"), (403, "app_scope_missing"),
                                       (401, "authorization_required"), (502, "result_unknown")])
def test_permission_failure_or_unknown_is_not_an_empty_success_or_retry(catalog, monkeypatch, status, code):
    ctx = catalog
    attempts = []

    def run(owner, args, **kwargs):
        attempts.append(args)
        raise FeishuError("synthetic failure", status, code=code)

    monkeypatch.setattr(cli, "run", run)
    with pytest.raises(FeishuError) as error:
        ctx.service.refresh_objects("alice")
    assert error.value.status_code == status and error.value.code == code
    assert len(attempts) == 1 and "groups_read" not in ctx.events
    assert ctx.cache.snapshot("alice", BINDING)["objects"] == []


@pytest.mark.parametrize("change", ["owner", "app_id", "sender_open_id", "connection_id", "tenant_key"])
def test_binding_change_during_contact_read_cannot_fill_new_connection(catalog, monkeypatch, change):
    ctx = catalog
    initial = deepcopy(ctx.binding)

    def run(owner, args, **kwargs):
        ctx.binding[change] += "-changed"
        return ctx.response

    monkeypatch.setattr(cli, "run", run)
    with pytest.raises(FeishuError) as error:
        ctx.service.refresh_objects("alice")
    assert error.value.status_code == 409 and "groups_read" not in ctx.events
    ctx.binding = initial
    assert ctx.cache.snapshot("alice", initial)["objects"] == []


def test_actual_cli_identity_mismatch_after_search_blocks_cache(catalog, monkeypatch):
    ctx = catalog
    calls = []

    def verify(owner):
        calls.append(owner)
        if len(calls) > 1:
            raise FeishuError("synthetic profile switched", 409, code="connection_changed")
        return USER

    monkeypatch.setattr(ctx.service, "user_token", verify)
    with pytest.raises(FeishuError):
        ctx.service.refresh_objects("alice")
    assert len(ctx.calls) == 1 and "groups_read" not in ctx.events
    assert ctx.cache.snapshot("alice", BINDING)["objects"] == []


@pytest.mark.parametrize("raw", [None, {}, {"ok": False, "error": {"type": "permission"}},
    {"ok": True, "identity": "bot", "data": {"users": [], "has_more": False}},
    {"ok": True, "identity": "user", "data": {"items": [], "has_more": False}},
    {"ok": True, "identity": "user", "data": {"users": None, "has_more": False}},
    {"ok": True, "identity": "user", "data": {"users": [], "has_more": "false"}},
    {"ok": True, "identity": "user", "data": {"users": []}},
])
def test_unverified_shape_is_never_treated_as_empty_directory(catalog, raw):
    ctx = catalog
    ctx.response = raw
    with pytest.raises(FeishuError):
        ctx.service.refresh_objects("alice")
    assert "groups_read" not in ctx.events
    assert ctx.cache.snapshot("alice", BINDING)["objects"] == []


@pytest.mark.parametrize("row", [
    {"open_id": "oc_wrong", "localized_name": "合成成员"},
    {"open_id": "ou_wrong", "name": "旧接口字段"},
    {"open_id": "ou_wrong", "localized_name": " "},
    {"open_id": "ou_wrong", "localized_name": "a\x00b"},
    {"open_id": "ou_wrong", "localized_name": "x" * 501},
])
def test_malformed_contact_page_has_no_partial_contact_writes(catalog, row):
    ctx = catalog
    ctx.response["data"]["users"].append(row)
    with pytest.raises(FeishuError):
        ctx.service.refresh_objects("alice")
    assert ctx.cache.snapshot("alice", BINDING)["objects"] == []


def test_oversized_page_rejected_without_continuing_or_partial_writes(catalog):
    ctx = catalog
    one = ctx.response["data"]["users"][0]
    ctx.response["data"]["users"] = [{**one, "open_id": "ou_" + str(i)} for i in range(31)]
    with pytest.raises(FeishuError):
        ctx.service.refresh_objects("alice")
    assert len(ctx.calls) == 1 and "groups_read" not in ctx.events
    assert ctx.cache.snapshot("alice", BINDING)["objects"] == []


def test_wrong_owner_cannot_run_cli(catalog):
    with pytest.raises(FeishuError) as error:
        catalog.service.refresh_objects("bob")
    assert error.value.status_code == 403 and catalog.calls == []


def test_refresh_endpoint_exposes_contact_page_has_more_and_partial(catalog, monkeypatch):
    from app.routers import feishu, feishu_object_hotwords as routes
    from app.services.auth_service import get_current_user

    monkeypatch.setattr(feishu, "principal", lambda request: ("alice", "local-alice"))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser("local-alice")
    with TestClient(app) as client:
        response = client.post("/api/feishu/object-hotwords/refresh")
    assert response.status_code == 200
    assert response.json()["partial"] is True and response.json()["has_more"] is True
    assert {item["kind"] for item in response.json()["objects"]} == {"contact", "group"}
    assert len(catalog.calls) == 1
