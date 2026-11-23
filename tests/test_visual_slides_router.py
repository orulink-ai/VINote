"""TDD tests for visual_slides router, note.py /artifacts/visuals/ PNG-only serving & config."""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import sys
import types
from types import SimpleNamespace
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import pytest

from app.config import Settings
from app.routers.visual_slides import create_visual_slides_router
from app.services.task_artifact_service import TaskArtifactService
from app.services.visual_slide_service import PROTOCOL


def _make_png() -> bytes:
    img = Image.new("RGB", (64, 36), (248, 250, 252))
    ImageDraw.Draw(img).rectangle([4, 4, 20, 20], fill=(29, 78, 216))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_task(tmp_path: Path, *, owner: str = "alice", status: str = "success"):
    artifacts = TaskArtifactService(tmp_path / "output")
    task_id = str(uuid.uuid4())
    folder = artifacts.create_task_dir(task_id)
    (folder / ".task_id").write_text(task_id, encoding="utf-8")
    (folder / "recording_owner").write_text(owner, encoding="utf-8")
    md = "# 会议\n\n## 要点\n\n内容。\n"
    (folder / "note.md").write_text(md, encoding="utf-8")
    (folder / "result.json").write_text(json.dumps({"markdown": md, "title": "会议"}), encoding="utf-8")
    (folder / "status.json").write_text(json.dumps({"status": status, "stage": status}), encoding="utf-8")
    return artifacts, task_id, folder


def _import_note_router(monkeypatch):
    """Import real app.routers.note even when optional bs4 is absent in local Python."""
    try:
        from app.routers import note as note_router
        return note_router
    except ModuleNotFoundError as exc:
        if exc.name != "bs4":
            raise
        stub_bs4 = types.ModuleType("bs4")
        stub_bs4.BeautifulSoup = object
        monkeypatch.setitem(sys.modules, "bs4", stub_bs4)
        from app.routers import note as note_router
        return note_router


def test_config_validates_visual_slides_settings():
    with pytest.raises(ValueError):
        Settings(visual_slides_max_count=5)
    with pytest.raises(ValueError):
        Settings(visual_slides_max_count=-1)
    with pytest.raises(ValueError):
        Settings(visual_renderer_url="http://192.168.1.50:9300/render")
    with pytest.raises(ValueError):
        Settings(visual_renderer_url="file:///etc/passwd")
    ok = Settings(visual_slides_max_count=3, visual_renderer_url="http://127.0.0.1:9300/render")
    assert ok.visual_slides_auto_generate is False
    assert ok.visual_slides_enabled is True


def test_visual_slides_router_auth_readonly_get_and_dedup_post(tmp_path):
    artifacts, task_id, folder = _create_task(tmp_path, owner="alice")
    current_user = {"value": None}
    runner_calls: list[tuple[str, str, bool]] = []

    def principal():
        if current_user["value"] is None:
            raise HTTPException(401, "Unauthorized")
        return SimpleNamespace(user_id=current_user["value"])

    def fake_runner(arts, owner, tid, *, force=False):
        runner_calls.append((owner, tid, force))
        vdir = folder / "visuals"
        vdir.mkdir(exist_ok=True)
        current_md = json.loads((folder / "result.json").read_text(encoding="utf-8"))["markdown"]
        (vdir / "manifest.json").write_text(
            json.dumps({
                "protocol": PROTOCOL,
                "task_id": tid,
                "status": "ready",
                "error_code": None,
                "source_markdown_sha256": hashlib.sha256(current_md.encode("utf-8")).hexdigest(),
                "slide_count": 1,
                "dropped_count": 0,
                "slides": [],
            }),
            encoding="utf-8",
        )

    app = FastAPI()
    app.include_router(
        create_visual_slides_router(artifacts=artifacts, principal=principal, runner=fake_runner),
        prefix="/api",
    )

    with TestClient(app) as client:
        # 401 when unauthenticated
        assert client.get(f"/api/task/{task_id}/visual-slides").status_code == 401
        assert client.post(f"/api/task/{task_id}/visual-slides").status_code == 401

        # 404 for wrong owner
        current_user["value"] = "bob"
        resp_bob = client.get(f"/api/task/{task_id}/visual-slides")
        assert resp_bob.status_code == 404
        assert client.post(f"/api/task/{task_id}/visual-slides").status_code == 404
        assert runner_calls == []

        # GET is strictly read-only for owner and carries no-store / Vary headers
        current_user["value"] = "alice"
        resp_get = client.get(f"/api/task/{task_id}/visual-slides")
        assert resp_get.status_code == 200
        assert resp_get.headers["cache-control"] == "private, no-store"
        assert resp_get.headers["vary"] == "Cookie, Authorization"
        assert resp_get.json()["status"] == "idle"
        assert runner_calls == []

        # POST queues once and returns 202
        resp_post = client.post(f"/api/task/{task_id}/visual-slides")
        assert resp_post.status_code == 202
        assert resp_post.headers["cache-control"] == "private, no-store"
        assert resp_post.headers["vary"] == "Cookie, Authorization"
        assert len(runner_calls) == 1

        # Subsequent GET reflects persisted ready manifest
        resp_ready = client.get(f"/api/task/{task_id}/visual-slides")
        assert resp_ready.status_code == 200
        assert resp_ready.json()["status"] == "ready"

        # Subsequent POST without force returns existing fresh ready manifest (200) without re-running
        resp_post2 = client.post(f"/api/task/{task_id}/visual-slides")
        assert resp_post2.status_code == 200
        assert len(runner_calls) == 1

        # If note markdown changes, POST without force detects staleness and re-queues (202)
        updated_md = "# 会议\n\n## 要点\n\n已更新内容。\n"
        (folder / "result.json").write_text(
            json.dumps({"markdown": updated_md, "title": "会议"}), encoding="utf-8"
        )
        resp_post3 = client.post(f"/api/task/{task_id}/visual-slides")
        assert resp_post3.status_code == 202
        assert len(runner_calls) == 2


def test_visual_slides_router_get_reports_generating_while_retrying_over_stale_manifest(tmp_path):
    """Regression test: GET must report 'generating' (not stale failed/ready manifest) while active."""
    artifacts, task_id, folder = _create_task(tmp_path, owner="alice")
    vdir = folder / "visuals"
    vdir.mkdir()
    (vdir / "manifest.json").write_text(
        json.dumps({
            "protocol": PROTOCOL,
            "task_id": task_id,
            "status": "failed",
            "error_code": "render_failed",
            "slide_count": 0,
            "dropped_count": 0,
            "slides": [],
        }),
        encoding="utf-8",
    )

    from app.services import visual_slide_service as svc

    app = FastAPI()
    app.include_router(
        create_visual_slides_router(artifacts=artifacts, principal=lambda: "alice"),
        prefix="/api",
    )
    with TestClient(app) as client:
        # Idle with stale failed manifest -> returns failed manifest
        before = client.get(f"/api/task/{task_id}/visual-slides")
        assert before.status_code == 200
        assert before.json()["status"] == "failed"

        # While actively generating (retry / force rerun) -> GET must report 'generating', never stale 'failed'
        with svc._ACTIVE_VISUAL_TASKS_LOCK:
            svc._ACTIVE_VISUAL_TASKS.add(task_id)
        try:
            during = client.get(f"/api/task/{task_id}/visual-slides")
            assert during.status_code == 200
            assert during.json()["status"] == "generating"
            assert during.json()["error_code"] is None
        finally:
            with svc._ACTIVE_VISUAL_TASKS_LOCK:
                svc._ACTIVE_VISUAL_TASKS.discard(task_id)

        after = client.get(f"/api/task/{task_id}/visual-slides")
        assert after.status_code == 200
        assert after.json()["status"] == "failed"


def test_visual_slides_router_get_returns_200_for_renderer_unavailable_manifest(tmp_path):
    artifacts, task_id, folder = _create_task(tmp_path, owner="alice")
    vdir = folder / "visuals"
    vdir.mkdir()
    (vdir / "manifest.json").write_text(
        json.dumps({
            "protocol": PROTOCOL,
            "task_id": task_id,
            "status": "failed",
            "error_code": "renderer_unavailable",
            "slide_count": 0,
            "dropped_count": 0,
            "slides": [],
        }),
        encoding="utf-8",
    )
    app = FastAPI()
    app.include_router(
        create_visual_slides_router(artifacts=artifacts, principal=lambda: "alice"),
        prefix="/api",
    )
    with TestClient(app) as client:
        resp = client.get(f"/api/task/{task_id}/visual-slides")
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        assert resp.json()["error_code"] == "renderer_unavailable"


def test_note_artifact_route_serves_only_flat_regular_pngs_from_visuals(tmp_path, monkeypatch):
    note_router = _import_note_router(monkeypatch)
    artifacts, task_id, folder = _create_task(tmp_path, owner="alice")
    vdir = folder / "visuals"
    vdir.mkdir()
    png_bytes = _make_png()
    (vdir / "slide-01.png").write_bytes(png_bytes)
    (vdir / "slide-01.html").write_text("<html><body><script>alert(1)</script></body></html>", encoding="utf-8")
    (vdir / "manifest.json").write_text('{"secret": true}', encoding="utf-8")
    (vdir / "slide-01.svg").write_text("<svg/>", encoding="utf-8")
    (vdir / "slide-01.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    nested = vdir / "nested"
    nested.mkdir()
    (nested / "slide-01.png").write_bytes(png_bytes)

    victim = tmp_path / "victim.png"
    victim.write_bytes(png_bytes)
    (vdir / "symlink.png").symlink_to(victim)
    os.link(victim, vdir / "hardlink.png")

    access_allowed = {"ok": True}

    def fake_access(tid, user):
        if not access_allowed["ok"]:
            raise HTTPException(404, "Task not found")

    monkeypatch.setattr(note_router, "_require_recording_access", fake_access)
    monkeypatch.setattr(note_router, "_note_service", SimpleNamespace(artifact_service=artifacts))

    app = FastAPI()
    app.include_router(note_router.router, prefix="/api")

    with TestClient(app) as client:
        ok = client.get(f"/api/task/{task_id}/artifacts/visuals/slide-01.png")
        assert ok.status_code == 200
        assert ok.content == png_bytes
        assert ok.headers["content-type"] == "image/png"
        assert ok.headers["cache-control"] == "private, no-store"
        assert ok.headers["x-content-type-options"] == "nosniff"
        assert ok.headers["content-security-policy"] == "default-src 'none'; sandbox"

        for forbidden_path in (
            "visuals/slide-01.html",
            "visuals/manifest.json",
            "visuals/slide-01.svg",
            "visuals/slide-01.jpg",
            "visuals/nested/slide-01.png",
            "visuals/%2e%2e/note.md",
            "visuals/symlink.png",
            "visuals/hardlink.png",
        ):
            resp = client.get(f"/api/task/{task_id}/artifacts/{forbidden_path}")
            assert resp.status_code == 404, f"Expected 404 for {forbidden_path}, got {resp.status_code}"

        # Wrong owner rejected
        access_allowed["ok"] = False
        assert client.get(f"/api/task/{task_id}/artifacts/visuals/slide-01.png").status_code == 404

        # Symlinked visuals/ directory rejected even for authorized owner
        access_allowed["ok"] = True
        import shutil
        shutil.rmtree(vdir)
        outside = tmp_path / "outside_visuals"
        outside.mkdir()
        (outside / "slide-01.png").write_bytes(png_bytes)
        vdir.symlink_to(outside)
        assert client.get(f"/api/task/{task_id}/artifacts/visuals/slide-01.png").status_code == 404

        # O1: recording_deleted marker and symlinked task_dir rejected on visuals/
        vdir.unlink()
        vdir.mkdir()
        (vdir / "slide-01.png").write_bytes(png_bytes)
        (folder / "recording_deleted").write_text("1", encoding="utf-8")
        assert client.get(f"/api/task/{task_id}/artifacts/visuals/slide-01.png").status_code == 404
        (folder / "recording_deleted").unlink()

        escaped_dir = tmp_path / "escaped_task"
        escaped_dir.mkdir()
        (escaped_dir / "visuals").mkdir()
        (escaped_dir / "visuals" / "slide-01.png").write_bytes(png_bytes)
        symlink_task = artifacts.output_dir / "symlink-task"
        symlink_task.symlink_to(escaped_dir)
        monkeypatch.setattr(
            note_router,
            "_note_service",
            SimpleNamespace(artifact_service=SimpleNamespace(output_dir=artifacts.output_dir, find_task_dir=lambda tid: symlink_task)),
        )
        assert client.get(f"/api/task/{task_id}/artifacts/visuals/slide-01.png").status_code == 404


def test_visual_slides_router_rejects_unfinished_task_with_409(tmp_path):
    artifacts, task_id, _ = _create_task(tmp_path, owner="alice", status="summarizing")
    called = []
    app = FastAPI()
    app.include_router(
        create_visual_slides_router(artifacts=artifacts, principal=lambda: "alice", runner=lambda *a, **kw: called.append(1)),
        prefix="/api",
    )
    with TestClient(app) as client:
        assert client.post(f"/api/task/{task_id}/visual-slides").status_code == 409
        assert called == []


def test_app_factory_mounts_visual_slides_routes(monkeypatch):
    _import_note_router(monkeypatch)
    from app import create_app

    app = create_app()
    routes = {(r.path, frozenset(r.methods or ())) for r in app.routes if hasattr(r, "methods")}
    assert any(path == "/api/task/{task_id}/visual-slides" and "GET" in methods for path, methods in routes)
    assert any(path == "/api/task/{task_id}/visual-slides" and "POST" in methods for path, methods in routes)


def test_note_service_maybe_schedule_visual_slides_respects_flags_and_style(tmp_path, monkeypatch):
    import threading
    from app.models.audio import AudioDownloadResult
    from app.services import note_service as ns_mod
    from app.services import preferences_repository as pref_mod
    from app.services import visual_slide_service as vs_mod

    monkeypatch.setattr(
        pref_mod.PreferenceRepository,
        "visual_slides_auto_generate_enabled",
        lambda self, user_id: bool(ns_mod.settings.visual_slides_enabled and ns_mod.settings.visual_slides_auto_generate),
    )

    artifacts, task_id, folder = _create_task(tmp_path, owner="alice")
    svc = ns_mod.NoteService(artifact_service=artifacts)
    invoked = threading.Event()
    calls: list[tuple[str, str]] = []

    def fake_gen(arts, owner, tid, **kwargs):
        calls.append((owner, tid))
        invoked.set()
        return {"status": "empty"}

    monkeypatch.setattr(vs_mod, "generate_visual_slides_for_task", fake_gen)

    def make_ctx(*, style="meeting", presentation=None):
        return ns_mod.PipelineContext(
            task_id=task_id,
            task_dir=folder,
            audio_meta=AudioDownloadResult(file_path="", title="t", duration=10.0, video_id=task_id, platform="local"),
            style=style,
            summary_mode="default",
            extras=None,
            output_language="zh-CN",
            model_profile_id=None,
            stt_profile_id=None,
            model_name=None,
            api_key=None,
            base_url=None,
            user_id="alice",
            source_video_url=None,
            task_start_time=0.0,
            step_timings={},
            presentation=presentation,
        )

    # Default auto_generate=False never schedules
    monkeypatch.setattr(ns_mod.settings, "visual_slides_auto_generate", False)
    svc._maybe_schedule_visual_slides(make_ctx())
    assert not invoked.wait(timeout=0.1)

    # Non-meeting style or specialized comic presentation never schedules
    monkeypatch.setattr(ns_mod.settings, "visual_slides_auto_generate", True)
    svc._maybe_schedule_visual_slides(make_ctx(style="detailed"))
    svc._maybe_schedule_visual_slides(make_ctx(style="meeting", presentation="comic"))
    assert not invoked.wait(timeout=0.1)

    # Enabled + meeting + text presentation schedules non-blocking daemon thread
    svc._maybe_schedule_visual_slides(make_ctx(style="meeting", presentation=None))
    assert invoked.wait(timeout=2.0)
    assert calls == [("alice", task_id)]

