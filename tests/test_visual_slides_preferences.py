"""TDD tests for per-user visual_slides_auto_generate preference, DB migration, API & NoteService hook."""
from __future__ import annotations

import threading
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import Base, _ensure_user_preference_columns
from app.db_models import UserDB
from app.models.audio import AudioDownloadResult
from app.models.auth import AuthenticatedUser
from app.routers import preferences as preferences_router
from app.services.auth_service import get_current_user
from app.services.note_service import NoteService, PipelineContext
from app.services.preferences_repository import PreferenceRepository
from app.services.task_artifact_service import TaskArtifactService


def _isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "prefs_test.db"
    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    local_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )
    from app import db as db_mod
    from contextlib import contextmanager

    @contextmanager
    def _scope():
        session = local_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", local_session)
    monkeypatch.setattr(db_mod, "session_scope", _scope)
    from app.services import preferences_repository as repo_mod
    monkeypatch.setattr(repo_mod, "session_scope", _scope)

    with _scope() as session:
        session.add(UserDB(id="user-a", email="a@example.com", password_hash="hash"))
        session.add(UserDB(id="user-b", email="b@example.com", password_hash="hash"))
    return engine, _scope


def test_preferences_api_inherits_env_default_and_updates_independently(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "visual_slides_enabled", True)
    monkeypatch.setattr(settings, "visual_slides_auto_generate", False)

    current = {"user": AuthenticatedUser(user_id="user-a", email="a@example.com")}
    app = FastAPI()
    app.include_router(preferences_router.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: current["user"]

    with TestClient(app) as client:
        # Unset user inherits server defaults without fabricating a language
        r0 = client.get("/api/preferences")
        assert r0.status_code == 200
        assert r0.headers["cache-control"] == "private, no-store"
        assert r0.headers["vary"] == "Cookie, Authorization"
        assert r0.json() == {
            "language": None,
            "visual_slides_enabled": True,
            "visual_slides_auto_generate": False,
        }

        # Enabling visual_slides_auto_generate leaves language=None and isolates per user
        r1 = client.patch("/api/preferences", json={"visual_slides_auto_generate": True})
        assert r1.status_code == 200
        assert r1.headers["cache-control"] == "private, no-store"
        assert r1.headers["vary"] == "Cookie, Authorization"
        assert r1.json() == {
            "language": None,
            "visual_slides_enabled": True,
            "visual_slides_auto_generate": True,
        }

        current["user"] = AuthenticatedUser(user_id="user-b", email="b@example.com")
        r_b = client.get("/api/preferences")
        assert r_b.status_code == 200
        assert r_b.json()["visual_slides_auto_generate"] is False

        # Updating language for user-a preserves visual_slides_auto_generate=True
        current["user"] = AuthenticatedUser(user_id="user-a", email="a@example.com")
        r2 = client.patch("/api/preferences", json={"language": "zh-CN"})
        assert r2.status_code == 200
        assert r2.json() == {
            "language": "zh-CN",
            "visual_slides_enabled": True,
            "visual_slides_auto_generate": True,
        }

        # Explicit user opt-out overrides VISUAL_SLIDES_AUTO_GENERATE=true env default
        monkeypatch.setattr(settings, "visual_slides_auto_generate", True)
        r3 = client.patch("/api/preferences", json={"visual_slides_auto_generate": False})
        assert r3.status_code == 200
        assert r3.json() == {
            "language": "zh-CN",
            "visual_slides_enabled": True,
            "visual_slides_auto_generate": False,
        }

        # Empty PATCH rejected cleanly with 422
        r_empty = client.patch("/api/preferences", json={})
        assert r_empty.status_code == 422

        # Server kill switch blocks toggling visual_slides_auto_generate (409) but still allows language update
        monkeypatch.setattr(settings, "visual_slides_enabled", False)
        r_get_disabled = client.get("/api/preferences")
        assert r_get_disabled.status_code == 200
        assert r_get_disabled.json()["visual_slides_enabled"] is False

        r_blocked = client.patch("/api/preferences", json={"visual_slides_auto_generate": True})
        assert r_blocked.status_code == 409
        assert r_blocked.headers["cache-control"] == "private, no-store"
        assert r_blocked.headers["vary"] == "Cookie, Authorization"

        r_lang_ok = client.patch("/api/preferences", json={"language": "en"})
        assert r_lang_ok.status_code == 200
        assert r_lang_ok.json()["language"] == "en"


def test_legacy_sqlite_migration_adds_column_and_handles_not_null_language(tmp_path, monkeypatch):
    db_file = tmp_path / "legacy.db"
    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, email VARCHAR(255) NOT NULL, password_hash VARCHAR(255) NOT NULL)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE user_preferences ("
            "user_id VARCHAR(36) PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, "
            "language VARCHAR(16) NOT NULL DEFAULT 'en', "
            "updated_at TIMESTAMP)"
        )
        conn.exec_driver_sql("INSERT INTO users (id, email, password_hash) VALUES ('u1', 'u1@example.com', 'h')")
        conn.exec_driver_sql("INSERT INTO users (id, email, password_hash) VALUES ('u2', 'u2@example.com', 'h')")
        conn.exec_driver_sql("INSERT INTO user_preferences (user_id, language) VALUES ('u1', 'zh-CN')")

    from app import db as db_mod
    from app.services import preferences_repository as repo_mod
    from contextlib import contextmanager

    local_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)

    @contextmanager
    def _scope():
        session = local_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(repo_mod, "session_scope", _scope)
    monkeypatch.setattr(settings, "visual_slides_enabled", True)
    monkeypatch.setattr(settings, "visual_slides_auto_generate", False)

    _ensure_user_preference_columns()
    cols = {c["name"] for c in inspect(engine).get_columns("user_preferences")}
    assert "visual_slides_auto_generate" in cols

    repo = PreferenceRepository()
    # Existing user keeps language and inherits env default
    p1 = repo.get_preferences("u1")
    assert p1.language == "zh-CN"
    assert p1.visual_slides_auto_generate is False

    # New user toggling visual slides succeeds despite legacy NOT NULL language column, and language stays None
    p2 = repo.update_preferences("u2", visual_slides_auto_generate=True)
    assert p2.language is None
    assert p2.visual_slides_auto_generate is True

    # Verify DB row persisted cleanly
    with engine.connect() as conn:
        row = conn.execute(text("SELECT language, visual_slides_auto_generate FROM user_preferences WHERE user_id='u2'")).one()
        assert row[0] == ""
        assert bool(row[1]) is True


def test_note_service_maybe_schedule_visual_slides_honors_user_preference(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    repo = PreferenceRepository()
    artifacts = TaskArtifactService(tmp_path / "output")

    def _run_hook(owner: str, *, env_enabled: bool, env_auto: bool) -> list[tuple[str, str]]:
        monkeypatch.setattr(settings, "visual_slides_enabled", env_enabled)
        monkeypatch.setattr(settings, "visual_slides_auto_generate", env_auto)
        scheduled: list[tuple[str, str]] = []
        done = threading.Event()

        def fake_gen(arts, u, tid, **kwargs):
            scheduled.append((u, tid))
            done.set()

        from app.services import visual_slide_service as svc_mod
        monkeypatch.setattr(svc_mod, "generate_visual_slides_for_task", fake_gen)

        task_id = str(uuid.uuid4())
        folder = artifacts.create_task_dir(task_id)
        ctx = PipelineContext(
            task_id=task_id,
            task_dir=folder,
            audio_meta=AudioDownloadResult(file_path="", title="t", duration=10, platform="local", video_id="v"),
            style="meeting",
            summary_mode="default",
            extras=None,
            output_language="zh-CN",
            model_profile_id=None,
            stt_profile_id=None,
            model_name=None,
            api_key=None,
            base_url=None,
            user_id=owner,
            source_video_url=None,
            task_start_time=0.0,
            step_timings={},
            presentation=None,
        )
        ns = object.__new__(NoteService)
        ns.artifact_service = artifacts
        ns._maybe_schedule_visual_slides(ctx)
        done.wait(timeout=0.3)
        return scheduled

    # 1. Env default False + user-a explicitly enabled -> schedules!
    repo.update_preferences("user-a", visual_slides_auto_generate=True)
    assert len(_run_hook("user-a", env_enabled=True, env_auto=False)) == 1

    # 2. Env default False + user-b unset -> does NOT schedule
    assert _run_hook("user-b", env_enabled=True, env_auto=False) == []

    # 3. Env default True + user-b unset -> schedules!
    assert len(_run_hook("user-b", env_enabled=True, env_auto=True)) == 1

    # 4. Env default True + user-a explicitly opted out -> does NOT schedule!
    repo.update_preferences("user-a", visual_slides_auto_generate=False)
    assert _run_hook("user-a", env_enabled=True, env_auto=True) == []

    # 5. Server kill switch off + user-a enabled -> does NOT schedule!
    repo.update_preferences("user-a", visual_slides_auto_generate=True)
    assert _run_hook("user-a", env_enabled=False, env_auto=True) == []


def test_preferences_endpoints_require_authentication():
    app = FastAPI()
    app.include_router(preferences_router.router, prefix="/api")
    with TestClient(app) as client:
        assert client.get("/api/preferences").status_code == 401
        assert client.patch("/api/preferences", json={"visual_slides_auto_generate": True}).status_code == 401


def test_concurrent_first_insert_recovers_from_pk_integrity_error(tmp_path, monkeypatch):
    _, scope = _isolated_db(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "visual_slides_enabled", True)
    monkeypatch.setattr(settings, "visual_slides_auto_generate", False)

    # Simulate another request inserting user-a's language row right between db.get() and db.flush()
    from app.services import preferences_repository as repo_mod
    real_scope = repo_mod.session_scope
    from contextlib import contextmanager

    @contextmanager
    def racing_scope():
        with real_scope() as session:
            real_get = session.get
            raced = {"done": False}

            def racing_get(entity, ident, *args, **kwargs):
                if not raced["done"] and ident == "user-a":
                    raced["done"] = True
                    # Commit a competing language row from a separate session before returning None
                    with real_scope() as winner:
                        from app.db_models import UserPreferenceDB
                        winner.add(UserPreferenceDB(user_id="user-a", language="zh-CN"))
                    return None
                return real_get(entity, ident, *args, **kwargs)

            session.get = racing_get  # type: ignore[method-assign]
            yield session

    monkeypatch.setattr(repo_mod, "session_scope", racing_scope)
    repo = PreferenceRepository()
    result = repo.update_preferences("user-a", visual_slides_auto_generate=True)
    assert result.language == "zh-CN"
    assert result.visual_slides_auto_generate is True


def test_init_db_cloud_postgres_runs_schema_qualified_if_not_exists_before_protect(monkeypatch):
    from contextlib import contextmanager
    from app import db as db_mod
    from app.services import workspace_bootstrap

    executed: list[str] = []
    call_order: list[str] = []

    class FakeQuoter:
        @staticmethod
        def quote(ident: str) -> str:
            return f'"{ident}"'

    class FakeDialect:
        name = "postgresql"
        identifier_preparer = FakeQuoter()

    class FakeScalar:
        @staticmethod
        def scalar_one() -> str:
            return "public"

    class FakeConnection:
        dialect = FakeDialect()

        def exec_driver_sql(self, sql: str):
            executed.append(sql)
            if sql == "SELECT current_schema()":
                return FakeScalar()
            return None

    class FakeEngine:
        dialect = FakeDialect()

        @contextmanager
        def begin(self):
            yield FakeConnection()

    class FakeInspector:
        @staticmethod
        def get_table_names():
            return ["users", "user_preferences"]

    monkeypatch.setattr(settings, "workspace_cloud_runtime", True)
    monkeypatch.setattr(db_mod, "engine", FakeEngine())
    monkeypatch.setattr(db_mod, "inspect", lambda target: FakeInspector())
    monkeypatch.setattr(db_mod.Base.metadata, "create_all", lambda bind=None: call_order.append("create_all"))
    monkeypatch.setattr(
        workspace_bootstrap,
        "protect_api_tables",
        lambda conn, tables: call_order.append("protect_api_tables"),
    )

    real_ensure = db_mod._ensure_user_preference_columns

    def tracked_ensure(conn=None):
        call_order.append("ensure_user_preference_columns")
        return real_ensure(conn)

    monkeypatch.setattr(db_mod, "_ensure_user_preference_columns", tracked_ensure)
    db_mod.init_db()

    assert call_order == ["create_all", "ensure_user_preference_columns", "protect_api_tables"]
    assert 'ALTER TABLE "public"."user_preferences" ADD COLUMN IF NOT EXISTS visual_slides_auto_generate BOOLEAN' in executed

