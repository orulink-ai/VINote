"""Authorization URL scopes only: no real OAuth, messages or credential reads."""
import ast
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app.services import feishu_service as module
from app.services import feishu_application_service as applications
from test_feishu_delivery import service  # noqa: F401

PREVIOUS = "offline_access docx:document docs:permission.member:create docs:permission.member:auth docs:permission.setting:read docs:permission.setting:write_only drive:drive.metadata:readonly wiki:space:read wiki:node:read wiki:node:create im:chat:read"
ADDITIONS = {"docx:document.block:convert", "contact:user:search"}


def configured_scope(environment=None):
    # Evaluate the actual config field in isolation; never load a real env/secret.
    tree = ast.parse((Path(__file__).parents[1] / "app/config.py").read_text(encoding="utf-8"))
    settings = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings")
    field = next(n for n in settings.body if isinstance(n, ast.AnnAssign) and n.target.id == "feishu_scopes")
    return eval(compile(ast.Expression(field.value), "scope-config", "eval"),
                {"__builtins__": {}, "os": SimpleNamespace(getenv=lambda key, default: default if environment is None else environment)})


def test_default_requests_exactly_two_new_permissions(service, monkeypatch):
    scope = configured_scope()
    assert set(scope.split()) == set(PREVIOUS.split()) | ADDITIONS
    assert len(scope.split()) == len(set(scope.split()))
    monkeypatch.setattr(module.settings, "feishu_scopes", scope)
    monkeypatch.setattr(service, "request", lambda *a, **k: pytest.fail("OAuth URL creation makes no provider request"))
    url = service.authorize("a")["url"]
    query = parse_qs(urlsplit(url).query)
    assert set(query["scope"][0].split()) == set(PREVIOUS.split()) | ADDITIONS
    assert query["client_id"] == ["app-test"]
    assert query["redirect_uri"] == ["https://notes.example/api/feishu/callback"]
    assert set(query) == {"client_id", "redirect_uri", "scope", "state"}
    # Requested permissions never become grants on the old connection.
    assert not service.status("a")["capabilities"]["contact_search"]
    assert not service.status("a")["markdown_conversion_preflight"]["user_grant_available"]


@pytest.mark.parametrize("override", [PREVIOUS, "offline_access docx:document", ""])
def test_explicit_environment_is_not_silently_expanded(service, monkeypatch, override):
    scope = configured_scope(override)
    assert scope == override
    monkeypatch.setattr(module.settings, "feishu_scopes", scope)
    query = parse_qs(urlsplit(service.authorize("a")["url"]).query, keep_blank_values=True)
    assert query["scope"] == [override]


def test_owner_application_uses_service_scope_and_its_own_client(service, monkeypatch):
    monkeypatch.setattr(applications, "session_scope", module.session_scope)
    monkeypatch.setattr(module.settings, "feishu_scopes", configured_scope())
    monkeypatch.setattr(module.FeishuService, "request", lambda *a, **k: {"tenant_access_token": "synthetic-probe"})
    applications.save_application("a", {"app_id": "cli_personal", "app_secret": "synthetic-test-only",
        "tenant_key": "company", "document_domain": "https://company.feishu.cn"})
    query = parse_qs(urlsplit(service.for_owner("a").authorize("a")["url"]).query)
    assert query["client_id"] == ["cli_personal"]
    assert set(query["scope"][0].split()) == set(PREVIOUS.split()) | ADDITIONS
    assert "synthetic-test-only" not in str(query)
    assert applications.application_config("b").feishu_app_id == "app-test"
