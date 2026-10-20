"""Synthetic, device-only object aliases. No CLI, Feishu or model calls."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import subprocess
import urllib.request

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.auth import AuthenticatedUser
from app.models.feishu_object_hotwords import FeishuObjectAliasDB, FeishuObjectDB
from app.services import feishu_object_hotwords as module


BINDING = {"owner": "alice", "app_id": "cli_synthetic", "sender_open_id": "ou_sender",
           "connection_id": "connection-1", "tenant_key": "synthetic-tenant"}
OBJECTS = [{"id": "ou_alpha", "name": "甲成员", "kind": "contact"},
           {"id": "oc_team", "name": "项目组", "kind": "group"}]


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("hotwords tests must not access network or CLI")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


@pytest.fixture
def store(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "hotwords.db").as_posix(),
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[FeishuObjectDB.__table__, FeishuObjectAliasDB.__table__])
    sessions = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def scope():
        with sessions.begin() as db:
            yield db

    current = {"value": deepcopy(BINDING)}
    service = module.FeishuObjectHotwordsService(
        binding_provider=lambda owner: current["value"], cli_enabled=lambda: True,
        session_factory=scope)
    yield service, current, sessions
    engine.dispose()


def test_empty_refresh_is_partial_and_does_not_invent_directory_access(store):
    service, _, _ = store
    assert service.refresh("alice", BINDING) == {"objects": [], "aliases": [], "partial": True}


def test_seen_objects_merge_and_drop_private_provider_fields(store):
    service, _, sessions = store
    service.record_objects("alice", BINDING, [{**OBJECTS[0], "email": "private@example.invalid",
                                              "selection_token": "must-not-persist"}])
    service.record_objects("alice", BINDING, OBJECTS[1:])
    result = service.snapshot("alice", BINDING)
    assert sorted(result["objects"], key=lambda item: item["id"]) == sorted(OBJECTS, key=lambda item: item["id"])
    assert result["partial"] is True and result["updated_at"] > 0
    with sessions() as db:
        assert len(db.scalars(select(FeishuObjectDB)).all()) == 2
        assert "must-not-persist" not in repr(result)


def test_binding_hash_is_canonical_and_contains_no_raw_binding(store):
    service, _, sessions = store
    service.record_objects("alice", dict(reversed(list(BINDING.items()))), OBJECTS)
    assert len(service.snapshot("alice", BINDING)["objects"]) == 2
    with sessions() as db:
        row = db.scalars(select(FeishuObjectDB)).first()
        assert len(row.binding_hash) == 64
        assert not hasattr(row, "connection_id")


def test_explicit_empty_tenant_does_not_collapse_known_tenant_binding(store):
    service, current, _ = store
    service.record_objects("alice", BINDING, OBJECTS)
    current["value"] = {**BINDING, "tenant_key": ""}
    assert service.snapshot("alice", current["value"])["objects"] == []


def test_binding_cannot_claim_another_owner(store):
    service, _, _ = store
    with pytest.raises(HTTPException) as error:
        service.record_objects("bob", BINDING, OBJECTS)
    assert error.value.status_code == 409


@pytest.mark.parametrize("change", ["owner", "app_id", "sender_open_id", "connection_id", "tenant_key"])
def test_cache_alias_and_delete_are_isolated(store, change):
    service, current, _ = store
    service.record_objects("alice", BINDING, OBJECTS)
    alias = service.add_alias("alice", BINDING, "项目伙伴", "ou_alpha")
    owner, binding = "alice", deepcopy(BINDING)
    if change == "owner":
        owner = "bob"
        binding["owner"] = owner
    else:
        binding[change] += "-other"
    current["value"] = binding
    assert service.snapshot(owner, binding) == {"objects": [], "aliases": [], "partial": True}
    assert service.resolve(owner, binding, "项目伙伴") == []
    with pytest.raises(HTTPException) as error:
        service.delete_alias(owner, binding, alias["id"])
    assert error.value.status_code == 404


def test_alias_targets_only_seen_object_and_is_idempotent(store):
    service, _, sessions = store
    with pytest.raises(HTTPException) as error:
        service.add_alias("alice", BINDING, "伙伴", "ou_alpha")
    assert error.value.status_code == 404
    service.record_objects("alice", BINDING, OBJECTS)
    first = service.add_alias("alice", BINDING, "  伙伴  ", "ou_alpha")
    assert first == service.add_alias("alice", BINDING, "伙伴", "ou_alpha")
    with pytest.raises(HTTPException) as conflict:
        service.add_alias("alice", BINDING, "伙伴", "oc_team")
    assert conflict.value.status_code == 409
    with sessions() as db:
        assert len(db.scalars(select(FeishuObjectAliasDB)).all()) == 1


def test_concurrent_alias_confirmation_is_one_atomic_binding(store):
    service, _, sessions = store
    service.record_objects("alice", BINDING, OBJECTS)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.add_alias("alice", BINDING, "伙伴", "ou_alpha"), range(4)))
    assert len({item["id"] for item in results}) == 1
    with sessions() as db:
        assert len(db.scalars(select(FeishuObjectAliasDB)).all()) == 1


def test_resolve_exact_normalized_alias_and_name_never_fuzzy_sends(store):
    service, _, _ = store
    service.record_objects("alice", BINDING, OBJECTS)
    service.add_alias("alice", BINDING, "Partner", "ou_alpha")
    result = service.resolve("alice", BINDING, "ＰＡＲＴＮＥＲ")
    assert result == [OBJECTS[0]]
    assert service.resolve("alice", BINDING, "甲成员") == [OBJECTS[0]]
    assert service.resolve("alice", BINDING, "甲") == []


def test_same_names_and_alias_name_collision_are_ambiguous(store):
    service, _, _ = store
    service.record_objects("alice", BINDING, [OBJECTS[0], {"id": "ou_beta", "name": "甲成员", "kind": "contact"}])
    result = service.resolve("alice", BINDING, "甲成员")
    assert {item["id"] for item in result} == {"ou_alpha", "ou_beta"}
    service.add_alias("alice", BINDING, "甲成员", "ou_alpha")
    assert len(service.resolve("alice", BINDING, "甲成员")) == 2


def test_rename_preserves_real_identity_and_updates_alias_display(store):
    service, _, _ = store
    service.record_objects("alice", BINDING, OBJECTS)
    alias = service.add_alias("alice", BINDING, "伙伴", "ou_alpha")
    service.record_objects("alice", BINDING, [{**OBJECTS[0], "name": "甲成员新名"}])
    result = service.snapshot("alice", BINDING)
    assert result["aliases"] == [{**alias, "target_name": "甲成员新名"}]
    service.delete_alias("alice", BINDING, alias["id"])
    assert service.resolve("alice", BINDING, "伙伴") == []
    assert len(service.snapshot("alice", BINDING)["objects"]) == 2


@pytest.mark.parametrize("alias", ["", " ", "x" * 51, "a\nb", "a\x00b", "a\u200bb"])
def test_invalid_alias_rejected_for_non_http_callers(store, alias):
    service, _, _ = store
    service.record_objects("alice", BINDING, OBJECTS)
    with pytest.raises(HTTPException) as error:
        service.add_alias("alice", BINDING, alias, "ou_alpha")
    assert error.value.status_code == 422


@pytest.mark.parametrize("object_", [{"id": "oc_wrong", "name": "成员", "kind": "contact"},
                                    {"id": "ou_a", "name": "", "kind": "contact"},
                                    {"id": "ou_a", "name": "成员", "kind": "bot"}])
def test_bad_cache_batch_is_atomic(store, object_):
    service, _, _ = store
    with pytest.raises(HTTPException):
        service.record_objects("alice", BINDING, [OBJECTS[0], object_])
    assert service.snapshot("alice", BINDING)["objects"] == []


def test_cache_and_alias_budgets_fail_without_partial_writes(store, monkeypatch):
    service, _, _ = store
    monkeypatch.setattr(module, "MAX_OBJECTS", 1)
    with pytest.raises(HTTPException):
        service.record_objects("alice", BINDING, OBJECTS)
    assert service.snapshot("alice", BINDING)["objects"] == []
    service.record_objects("alice", BINDING, OBJECTS[:1])
    monkeypatch.setattr(module, "MAX_ALIASES", 1)
    service.add_alias("alice", BINDING, "伙伴一", "ou_alpha")
    with pytest.raises(HTTPException):
        service.add_alias("alice", BINDING, "伙伴二", "ou_alpha")
    assert len(service.snapshot("alice", BINDING)["aliases"]) == 1


def test_binding_change_during_read_only_refresh_discards_late_result(store):
    service, current, _ = store

    def provider(owner, binding):
        assert owner == "alice" and binding == BINDING
        current["value"] = {**BINDING, "connection_id": "connection-2"}
        return OBJECTS

    service.refresh_provider = provider
    with pytest.raises(HTTPException) as error:
        service.refresh("alice", BINDING)
    assert error.value.status_code == 409
    current["value"] = BINDING
    assert service.snapshot("alice", BINDING)["objects"] == []


def test_disabling_cli_during_cache_refresh_prevents_late_persistence(store):
    service, _, _ = store

    def provider(owner, binding):
        service.cli_enabled = lambda: False
        return OBJECTS

    service.refresh_provider = provider
    with pytest.raises(HTTPException) as error:
        service.refresh("alice", BINDING)
    assert error.value.status_code == 403
    service.cli_enabled = lambda: True
    assert service.snapshot("alice", BINDING)["objects"] == []


def test_refresh_failure_keeps_existing_cache_and_never_retries(store):
    service, _, _ = store
    service.record_objects("alice", BINDING, OBJECTS)
    calls = []

    def provider(*args):
        calls.append(1)
        raise TimeoutError("synthetic failure")

    service.refresh_provider = provider
    with pytest.raises(HTTPException) as error:
        service.refresh("alice", BINDING)
    assert error.value.status_code == 503 and calls == [1]
    assert len(service.snapshot("alice", BINDING)["objects"]) == 2


@pytest.mark.parametrize("binding", [{}, {**BINDING, "connection_id": ""},
                                      {**BINDING, "sender_open_id": "oc_not_user"},
                                      {**BINDING, "secret": "not-allowed"}])
def test_unverified_or_secret_bearing_binding_rejected(store, binding):
    service, _, _ = store
    with pytest.raises(HTTPException):
        service.record_objects("alice", binding, OBJECTS)


@pytest.fixture
def api(store, monkeypatch):
    from app.config import settings
    from app.routers import feishu, feishu_object_hotwords as routes
    from app.services.auth_service import get_current_user
    from app.services.feishu_service import FeishuService

    service, _, _ = store
    monkeypatch.setattr(module, "service", service)
    monkeypatch.setattr(settings, "desktop_runtime", True)
    monkeypatch.setattr(settings, "workspace_cloud_runtime", False)
    monkeypatch.setattr(settings, "content_cloud_runtime", False)
    monkeypatch.setattr(feishu, "principal", lambda request: ("alice", "local-alice"))

    class Provider:
        group_reads = 0
        verified = False

        def __init__(self):
            self.events = []

        def user_token(self, owner):
            self.events.append(("verify_cli", owner))
            self.verified = True

        def contact_binding(self, owner):
            assert self.verified, "CLI identity must be verified before reading DB binding"
            self.events.append(("read_binding", owner))
            return service.current_binding(owner)

        def groups(self, owner):
            self.group_reads += 1
            service.record_objects(owner, self.contact_binding(owner), OBJECTS[1:])
            return [{"chat_id": "oc_team", "name": "项目组"}]

        def refresh_objects(self, owner):
            self.groups(owner)
            return {"has_more": False, "partial": True}

    provider = Provider()
    monkeypatch.setattr(FeishuService, "for_owner", lambda self, owner: provider)
    app = FastAPI()
    app.state.hotword_provider = provider
    app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser("local-alice")
    with TestClient(app) as client:
        yield client, service, app


def test_http_cache_alias_refresh_delete_contract(api):
    client, service, _ = api
    service.record_objects("alice", BINDING, OBJECTS)
    response = client.get("/api/feishu/object-hotwords")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    result = client.post("/api/feishu/object-hotwords", json={"alias": "伙伴", "target_id": "ou_alpha"})
    assert result.status_code == 200
    assert result.json()["objects"] == response.json()["objects"]
    assert result.json()["partial"] is True
    alias = result.json()["aliases"][0]
    assert set(alias) == {"id", "alias", "target_id", "target_name", "kind"}
    assert client.post("/api/feishu/object-hotwords/refresh").json()["aliases"] == [alias]
    deleted = client.delete("/api/feishu/object-hotwords/" + alias["id"])
    assert deleted.status_code == 200 and deleted.json()["aliases"] == []
    assert deleted.json()["objects"] == response.json()["objects"]


def test_http_verifies_real_cli_identity_before_db_binding(api):
    client, _, app = api
    assert client.get("/api/feishu/object-hotwords").status_code == 200
    assert app.state.hotword_provider.events == [("verify_cli", "alice"), ("read_binding", "alice")]


@pytest.mark.parametrize("status", [401, 409])
@pytest.mark.parametrize("method,path,body", [
    ("GET", "", None), ("POST", "/refresh", None),
    ("POST", "", {"alias": "伙伴", "target_id": "ou_alpha"}),
    ("DELETE", "/synthetic-alias", None),
])
def test_cli_profile_mismatch_or_expiry_blocks_all_cache_access(api, monkeypatch, status, method, path, body):
    client, service, app = api
    service.record_objects("alice", BINDING, OBJECTS)
    alias = service.add_alias("alice", BINDING, "伙伴", "ou_alpha")
    calls = []

    def verify(owner):
        calls.append(owner)
        raise HTTPException(status, "synthetic CLI identity rejected")

    def forbidden(*args):
        raise AssertionError("rejected CLI identity must not read binding, cache, refresh or mutate aliases")

    monkeypatch.setattr(app.state.hotword_provider, "user_token", verify)
    monkeypatch.setattr(app.state.hotword_provider, "contact_binding", forbidden)
    monkeypatch.setattr(app.state.hotword_provider, "groups", forbidden)
    with monkeypatch.context() as guarded:
        for operation in ("snapshot", "refresh", "add_alias", "delete_alias"):
            guarded.setattr(service, operation, forbidden)
        response = client.request(method, "/api/feishu/object-hotwords" + path,
                                  **({"json": body} if body is not None else {}))
    assert response.status_code == status and calls == ["alice"]
    assert "甲成员" not in response.text and "项目组" not in response.text
    assert service.snapshot("alice", BINDING)["aliases"] == [alias]


def test_http_refresh_reads_groups_once_and_keeps_search_cache(api):
    client, service, app = api
    service.record_objects("alice", BINDING, OBJECTS[:1])
    result = client.post("/api/feishu/object-hotwords/refresh")
    assert result.status_code == 200 and result.json()["partial"] is True
    assert {item["id"] for item in result.json()["objects"]} == {"ou_alpha", "oc_team"}
    assert app.state.hotword_provider.group_reads == 1


def test_http_refresh_error_keeps_cache_without_retry(api, monkeypatch):
    client, service, app = api
    service.record_objects("alice", BINDING, OBJECTS[:1])
    calls = []

    def groups(owner):
        calls.append(owner)
        raise HTTPException(502, "synthetic unavailable")

    monkeypatch.setattr(app.state.hotword_provider, "groups", groups)
    assert client.post("/api/feishu/object-hotwords/refresh").status_code == 502
    assert calls == ["alice"]
    assert client.get("/api/feishu/object-hotwords").json()["objects"] == OBJECTS[:1]


def test_http_late_refresh_cannot_disclose_previous_binding(api, monkeypatch):
    client, service, app = api
    service.record_objects("alice", BINDING, OBJECTS)

    def groups(owner):
        service.binding_provider = lambda owner: {**BINDING, "connection_id": "connection-2"}
        return []

    monkeypatch.setattr(app.state.hotword_provider, "groups", groups)
    assert client.post("/api/feishu/object-hotwords/refresh").status_code == 409
    assert client.get("/api/feishu/object-hotwords").json()["objects"] == []


def test_http_principal_must_match_authenticated_local_user(api, monkeypatch):
    from app.routers import feishu

    client, _, _ = api
    monkeypatch.setattr(feishu, "principal", lambda request: ("bob", "other-local-user"))
    assert client.get("/api/feishu/object-hotwords").status_code == 403


def test_default_lazy_provider_wiring_requires_no_configure_call(store, monkeypatch):
    from app.services import feishu_cli
    from app.services.feishu_service import FeishuService

    previous, _, _ = store

    class Provider:
        def contact_binding(self, owner):
            assert owner == "alice"
            return BINDING

    monkeypatch.setattr(feishu_cli, "enabled", lambda: True)
    monkeypatch.setattr(FeishuService, "for_owner", lambda self, owner: Provider())
    service = module.FeishuObjectHotwordsService(binding_provider=module._current_binding,
                                                cli_enabled=module._cli_enabled,
                                                session_factory=previous.session_factory)
    monkeypatch.setattr(module, "service", service)
    module.record_objects("alice", BINDING, OBJECTS)
    assert module.resolve("alice", BINDING, "甲成员") == OBJECTS[:1]


@pytest.mark.parametrize("gate", ["desktop", "workspace_cloud", "content_cloud", "cli", "binding"])
def test_all_routes_fail_closed_outside_verified_desktop_cli(api, monkeypatch, gate):
    from app.config import settings

    client, service, _ = api
    if gate == "desktop":
        monkeypatch.setattr(settings, "desktop_runtime", False)
    elif gate.endswith("cloud"):
        monkeypatch.setattr(settings, gate + "_runtime", True)
    elif gate == "cli":
        service.cli_enabled = lambda: False
    else:
        service.binding_provider = lambda owner: None
    for method, path, kwargs in [("GET", "", {}), ("POST", "/refresh", {}),
                                 ("POST", "", {"json": {"alias": "伙伴", "target_id": "ou_alpha"}}),
                                 ("DELETE", "/synthetic-id", {})]:
        response = client.request(method, "/api/feishu/object-hotwords" + path, **kwargs)
        assert response.status_code in (403, 409)


def test_http_rejects_untrusted_identity_fields_and_requires_authentication(api):
    from app.services.auth_service import get_current_user

    client, _, app = api
    assert client.post("/api/feishu/object-hotwords", json={
        "alias": "伙伴", "target_id": "ou_alpha", "owner": "bob", "binding": BINDING,
    }).status_code == 422

    def unauthenticated():
        raise HTTPException(401, "synthetic sign-out")

    app.dependency_overrides[get_current_user] = unauthenticated
    assert client.get("/api/feishu/object-hotwords").status_code == 401


def test_bearer_route_never_calls_cloud_principal(api, monkeypatch):
    from app.routers import feishu

    client, _, _ = api

    def forbidden(*args):
        raise AssertionError("desktop-only hotwords must never verify a cloud bearer")

    monkeypatch.setattr(feishu, "principal", forbidden)
    assert client.get("/api/feishu/object-hotwords", headers={"Authorization": "Bearer synthetic"}).status_code == 403
