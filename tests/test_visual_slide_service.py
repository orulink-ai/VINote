"""TDD tests for visual_slide_service orchestrator, repair bounds, dedup & security."""
from io import BytesIO
import json
import os
from pathlib import Path
import threading
import uuid

from PIL import Image, ImageDraw
import pytest

from app.services.task_artifact_service import TaskArtifactService
from app.services.visual_slide_renderer import (
    EXPECTED_HEIGHT,
    EXPECTED_WIDTH,
    GeometryAudit,
    RenderedSlide,
    VisualRendererUnavailableError,
)
from app.services.visual_slide_sanitizer import BUNDLED_FONT_URL
from app.services.visual_slide_service import (
    MAX_REPAIR_ATTEMPTS,
    PROTOCOL,
    VisualSlideSecurityError,
    generate_visual_slides_for_task,
    read_visual_slides_manifest,
)


def _sample_png(color=(29, 78, 216)) -> bytes:
    img = Image.new("RGB", (EXPECTED_WIDTH, EXPECTED_HEIGHT), (248, 250, 252))
    draw = ImageDraw.Draw(img)
    draw.rectangle([120, 120, 700, 360], fill=color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_rendered(*, passed: bool = True, issues: tuple[str, ...] = ()) -> RenderedSlide:
    png = _sample_png()
    return RenderedSlide(
        png_bytes=png,
        width=EXPECTED_WIDTH,
        height=EXPECTED_HEIGHT,
        png_sha256="a" * 64,
        geometry=GeometryAudit(passed=passed, issues=issues, metrics={"visible_text_chars": 80}),
        renderer_kind="chrome-cdp",
    )


def _create_completed_task(tmp_path: Path, *, owner: str = "alice", status: str = "success"):
    artifacts = TaskArtifactService(tmp_path / "output")
    task_id = str(uuid.uuid4())
    folder = artifacts.create_task_dir(task_id)
    (folder / ".task_id").write_text(task_id, encoding="utf-8")
    (folder / "recording_owner").write_text(owner, encoding="utf-8")
    md = "# 产品架构评审\n\n## 系统链路\n\n离线安全渲染链路。\n\n## 行动项\n\n- 交付视觉幻灯片\n"
    (folder / "note.md").write_text(md, encoding="utf-8")
    (folder / "result.json").write_text(
        json.dumps({"markdown": md, "title": "产品架构评审", "summary_mode": "default"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (folder / "status.json").write_text(
        json.dumps({"status": status, "stage": status, "message": "ok"}),
        encoding="utf-8",
    )
    return artifacts, task_id, folder, md


def _plan_json(count: int) -> str:
    slides = [
        {
            "index": i,
            "id": f"slide-0{i}",
            "title": f"核心图解 {i}",
            "caption": f"核心图解说明 {i}",
            "target_heading": "系统链路" if i == 1 else "行动项",
            "visual_rationale": "结构化呈现更清晰",
            "visual_brief": f"第 {i} 张定制布局",
            "key_facts": [f"事实 {i}"],
        }
        for i in range(1, count + 1)
    ]
    return json.dumps({"slides": slides}, ensure_ascii=False)


def test_zero_slides_plan_records_empty_and_leaves_markdown_untouched(tmp_path):
    artifacts, task_id, folder, orig_md = _create_completed_task(tmp_path)
    orig_status = (folder / "status.json").read_bytes()

    manifest = generate_visual_slides_for_task(
        artifacts,
        "alice",
        task_id,
        llm_complete=lambda sys, usr: '{"slides": []}',
        renderer=lambda doc: _make_rendered(),
    )
    assert manifest["protocol"] == PROTOCOL
    assert manifest["status"] == "empty"
    assert manifest["slides"] == []
    assert (folder / "note.md").read_text(encoding="utf-8") == orig_md
    assert json.loads((folder / "result.json").read_text(encoding="utf-8"))["markdown"] == orig_md
    assert (folder / "status.json").read_bytes() == orig_status
    assert read_visual_slides_manifest(artifacts, "alice", task_id)["status"] == "empty"


def test_full_lifecycle_generates_persists_disk_html_and_patches_markdown_idempotently(tmp_path):
    artifacts, task_id, folder, orig_md = _create_completed_task(tmp_path)
    orig_status = (folder / "status.json").read_bytes()

    def llm(system: str, user: str) -> str:
        if "Available ## Headings" in user:
            return _plan_json(2)
        return "<!DOCTYPE html><html><body><div class='slide'><h1>定制视图</h1><p>离线安全渲染</p></div></body></html>"

    manifest = generate_visual_slides_for_task(
        artifacts,
        "alice",
        task_id,
        llm_complete=llm,
        vlm_complete=lambda s, u, b: '{"passed": true, "issues": []}',
        renderer=lambda doc: _make_rendered(passed=True),
    )
    assert manifest["status"] == "ready"
    assert manifest["slide_count"] == 2
    assert len(manifest["slides"]) == 2

    # Disk artifacts exist; disk HTML has ZERO font URLs
    for idx in (1, 2):
        png_path = folder / "visuals" / f"slide-0{idx}.png"
        html_path = folder / "visuals" / f"slide-0{idx}.html"
        assert png_path.is_file() and html_path.is_file()
        disk_html = html_path.read_text(encoding="utf-8")
        assert BUNDLED_FONT_URL not in disk_html
        assert "font-src 'none'" in disk_html

    # Markdown and result.json updated idempotently; status.json untouched
    note_md = (folder / "note.md").read_text(encoding="utf-8")
    result_md = json.loads((folder / "result.json").read_text(encoding="utf-8"))["markdown"]
    assert note_md == result_md
    assert f"/api/task/{task_id}/artifacts/visuals/slide-01.png" in note_md
    assert f"/api/task/{task_id}/artifacts/visuals/slide-02.png" in note_md
    assert (folder / "status.json").read_bytes() == orig_status

    # Force regeneration produces idempotent Markdown (zero duplicates)
    generate_visual_slides_for_task(
        artifacts,
        "alice",
        task_id,
        force=True,
        llm_complete=llm,
        renderer=lambda doc: _make_rendered(passed=True),
    )
    note_md_2 = (folder / "note.md").read_text(encoding="utf-8")
    assert note_md_2.count("slide-01.png") == 1
    assert note_md_2.count("slide-02.png") == 1


def test_geometry_failure_triggers_max_one_repair_and_drops_unrepairable_keeping_good(tmp_path):
    artifacts, task_id, folder, _ = _create_completed_task(tmp_path)
    render_counts = {"slide-01": 0, "slide-02": 0}
    repair_calls = {"count": 0}

    def llm(system: str, user: str) -> str:
        if "Available ## Headings" in user:
            return _plan_json(2)
        if "Previous Slide HTML to Repair" in user:
            repair_calls["count"] += 1
            if "slide-01" in user:
                return "<div id='s1-fixed'><h1>Slide 1 Fixed</h1></div>"
            return "<div id='s2-still-bad'><h1>Slide 2 Still Bad</h1></div>"
        if "slide-01" in user:
            return "<div id='s1-init'><h1>Slide 1 Init</h1></div>"
        return "<div id='s2-init'><h1>Slide 2 Init</h1></div>"

    def fake_renderer(doc):
        if "s1-init" in doc.disk_html:
            render_counts["slide-01"] += 1
            return _make_rendered(passed=False, issues=("viewport_overflow_y:960>900",))
        if "s1-fixed" in doc.disk_html:
            render_counts["slide-01"] += 1
            return _make_rendered(passed=True)
        if "s2-init" in doc.disk_html or "s2-still-bad" in doc.disk_html:
            render_counts["slide-02"] += 1
            return _make_rendered(passed=False, issues=("text_overlap:3_pairs",))
        raise AssertionError("Unexpected slide HTML")

    manifest = generate_visual_slides_for_task(
        artifacts,
        "alice",
        task_id,
        llm_complete=llm,
        vlm_review_enabled=False,
        renderer=fake_renderer,
    )
    assert MAX_REPAIR_ATTEMPTS == 1
    assert render_counts["slide-01"] == 2
    assert render_counts["slide-02"] == 2  # initial + max 1 repair retry, NEVER 3!
    assert repair_calls["count"] == 2
    assert manifest["status"] == "ready"
    assert manifest["slide_count"] == 1
    assert manifest["dropped_count"] == 1
    assert manifest["slides"][0]["id"] == "slide-01"
    assert manifest["slides"][0]["repair_attempts"] == 1
    assert (folder / "visuals" / "slide-01.png").exists()
    assert not (folder / "visuals" / "slide-02.png").exists()


def test_vlm_unavailable_or_error_gracefully_accepts_geometry_passing_slide(tmp_path):
    artifacts, task_id, folder, _ = _create_completed_task(tmp_path)

    def llm(system: str, user: str) -> str:
        if "Available ## Headings" in user:
            return _plan_json(1)
        return "<div><h1>正常幻灯片</h1></div>"

    def broken_vlm(system: str, user: str, png: bytes) -> str:
        raise RuntimeError("VLM service 503 with secret=/private/key")

    manifest = generate_visual_slides_for_task(
        artifacts,
        "alice",
        task_id,
        llm_complete=llm,
        vlm_complete=broken_vlm,
        vlm_review_enabled=True,
        renderer=lambda doc: _make_rendered(passed=True),
    )
    assert manifest["status"] == "ready"
    assert manifest["slide_count"] == 1
    assert manifest["slides"][0]["vlm_reviewed"] is False
    raw_manifest = (folder / "visuals" / "manifest.json").read_text(encoding="utf-8")
    assert "secret=" not in raw_manifest


def test_chrome_unavailable_records_failed_without_touching_markdown_or_status(tmp_path):
    artifacts, task_id, folder, orig_md = _create_completed_task(tmp_path)
    orig_status = (folder / "status.json").read_bytes()

    def missing_renderer(doc):
        raise VisualRendererUnavailableError("chrome_unavailable")

    manifest = generate_visual_slides_for_task(
        artifacts,
        "alice",
        task_id,
        llm_complete=lambda s, u: _plan_json(1) if "Available ## Headings" in u else "<div><h1>X</h1></div>",
        renderer=missing_renderer,
    )
    assert manifest["status"] == "failed"
    assert manifest["error_code"] == "renderer_unavailable"
    assert manifest["slides"] == []
    assert (folder / "note.md").read_text(encoding="utf-8") == orig_md
    assert (folder / "status.json").read_bytes() == orig_status


def test_security_rejects_wrong_owner_task_id_deleted_unfinished_and_links(tmp_path):
    artifacts, task_id, folder, _ = _create_completed_task(tmp_path, owner="alice")

    # Wrong owner
    with pytest.raises(VisualSlideSecurityError):
        generate_visual_slides_for_task(artifacts, "bob", task_id, llm_complete=lambda s, u: '{"slides": []}')
    assert read_visual_slides_manifest(artifacts, "bob", task_id) is None

    # Unfinished task
    artifacts2, task_id2, _, _ = _create_completed_task(tmp_path / "u", owner="alice", status="summarizing")
    with pytest.raises(VisualSlideSecurityError):
        generate_visual_slides_for_task(artifacts2, "alice", task_id2, llm_complete=lambda s, u: '{"slides": []}')

    # recording_deleted marker
    (folder / "recording_deleted").write_text("1", encoding="utf-8")
    with pytest.raises(VisualSlideSecurityError):
        generate_visual_slides_for_task(artifacts, "alice", task_id, llm_complete=lambda s, u: '{"slides": []}')
    (folder / "recording_deleted").unlink()

    # Mismatched .task_id
    (folder / ".task_id").write_text(str(uuid.uuid4()), encoding="utf-8")
    with pytest.raises(VisualSlideSecurityError):
        generate_visual_slides_for_task(artifacts, "alice", task_id, llm_complete=lambda s, u: '{"slides": []}')
    (folder / ".task_id").write_text(task_id, encoding="utf-8")

    # Symlinked visuals/ directory rejected
    outside = tmp_path / "outside"
    outside.mkdir()
    (folder / "visuals").symlink_to(outside)
    with pytest.raises(VisualSlideSecurityError):
        generate_visual_slides_for_task(
            artifacts,
            "alice",
            task_id,
            llm_complete=lambda s, u: '{"slides": []}',
            renderer=lambda doc: _make_rendered(),
        )
    (folder / "visuals").unlink()

    # Hardlinked target file rejected without clobbering victim
    (folder / "visuals").mkdir()
    victim = tmp_path / "victim.json"
    victim.write_text("untouched", encoding="utf-8")
    os.link(victim, folder / "visuals" / "manifest.json")
    with pytest.raises(VisualSlideSecurityError):
        generate_visual_slides_for_task(
            artifacts,
            "alice",
            task_id,
            force=True,
            llm_complete=lambda s, u: '{"slides": []}',
            renderer=lambda doc: _make_rendered(),
        )
    assert victim.read_text(encoding="utf-8") == "untouched"


def test_concurrent_invocation_deduplicates_via_active_visual_tasks(tmp_path):
    artifacts, task_id, _, _ = _create_completed_task(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    llm_calls = {"count": 0}

    def slow_llm(system: str, user: str) -> str:
        llm_calls["count"] += 1
        entered.set()
        release.wait(timeout=5)
        return '{"slides": []}'

    results: list[dict] = []

    def worker():
        results.append(
            generate_visual_slides_for_task(
                artifacts,
                "alice",
                task_id,
                llm_complete=slow_llm,
                renderer=lambda doc: _make_rendered(),
            )
        )

    t1 = threading.Thread(target=worker)
    t1.start()
    assert entered.wait(timeout=2)

    # Second concurrent call returns immediately with status="generating"
    second = generate_visual_slides_for_task(
        artifacts,
        "alice",
        task_id,
        llm_complete=slow_llm,
        renderer=lambda doc: _make_rendered(),
    )
    assert second["status"] == "generating"
    release.set()
    t1.join(timeout=5)

    assert len(results) == 1
    assert results[0]["status"] == "empty"
    assert llm_calls["count"] == 1


def test_o1_manifest_reader_rejects_non_list_slides(tmp_path):
    artifacts, task_id, folder, _ = _create_completed_task(tmp_path)
    vdir = folder / "visuals"
    vdir.mkdir()
    (vdir / "manifest.json").write_text(
        json.dumps({"protocol": PROTOCOL, "task_id": task_id, "status": "ready", "slides": "bad"}),
        encoding="utf-8",
    )
    assert read_visual_slides_manifest(artifacts, "alice", task_id) is None


def test_g2_skips_vlm_when_doomed_after_final_geometry_fail_and_downscales_preview(tmp_path):
    from app.services import visual_slide_service as svc

    artifacts, task_id, _, _ = _create_completed_task(tmp_path)
    vlm_calls = {"count": 0}

    def llm(system: str, user: str) -> str:
        if "Available ## Headings" in user:
            return _plan_json(1)
        return "<div><h1>Always Failing Geometry</h1></div>"

    def vlm(system: str, user: str, png: bytes) -> str:
        vlm_calls["count"] += 1
        return '{"passed": false, "issues": ["overflow"]}'

    manifest = generate_visual_slides_for_task(
        artifacts,
        "alice",
        task_id,
        llm_complete=llm,
        vlm_complete=vlm,
        vlm_review_enabled=True,
        renderer=lambda doc: _make_rendered(passed=False, issues=("viewport_overflow_y:960>900",)),
    )
    assert manifest["status"] == "empty"
    # VLM called only on initial attempt (to inform repair), NOT wasted on doomed final retry!
    assert vlm_calls["count"] == 1

    # Verify VLM preview helper downscales 3200x1800 PNG to 1600x900 compact JPEG
    mime, preview = svc._encode_vlm_preview(_sample_png())
    assert mime == "image/jpeg"
    assert len(preview) <= 400 * 1024
    with Image.open(BytesIO(preview)) as img:
        assert img.size == (1600, 900)


def test_m1_force_rerun_empty_cleans_stale_files_and_strips_dangling_markdown_refs(tmp_path):
    artifacts, task_id, folder, orig_md = _create_completed_task(tmp_path)

    # First run creates slide-01.png and injects reference into note.md / result.json
    def llm_v1(system: str, user: str) -> str:
        if "Available ## Headings" in user:
            return _plan_json(1)
        return "<div><h1>Slide 1</h1></div>"

    m1 = generate_visual_slides_for_task(
        artifacts,
        "alice",
        task_id,
        llm_complete=llm_v1,
        vlm_review_enabled=False,
        renderer=lambda doc: _make_rendered(passed=True),
    )
    assert m1["status"] == "ready"
    assert (folder / "visuals" / "slide-01.png").exists()
    assert f"/api/task/{task_id}/artifacts/visuals/slide-01.png" in (folder / "note.md").read_text(encoding="utf-8")

    # Force rerun yielding empty plan must remove stale PNG/HTML AND strip dangling refs
    m2 = generate_visual_slides_for_task(
        artifacts,
        "alice",
        task_id,
        force=True,
        llm_complete=lambda s, u: '{"slides": []}',
        vlm_review_enabled=False,
        renderer=lambda doc: _make_rendered(passed=True),
    )
    assert m2["status"] == "empty"
    assert not (folder / "visuals" / "slide-01.png").exists()
    assert not (folder / "visuals" / "slide-01.html").exists()
    assert (folder / "note.md").read_text(encoding="utf-8") == orig_md
    assert json.loads((folder / "result.json").read_text(encoding="utf-8"))["markdown"] == orig_md

    # Regenerate slide-01, then force rerun where all slides fail geometry (not accepted) -> also strips dangling refs
    m3 = generate_visual_slides_for_task(
        artifacts,
        "alice",
        task_id,
        force=True,
        llm_complete=llm_v1,
        vlm_review_enabled=False,
        renderer=lambda doc: _make_rendered(passed=True),
    )
    assert m3["status"] == "ready"
    m4 = generate_visual_slides_for_task(
        artifacts,
        "alice",
        task_id,
        force=True,
        llm_complete=llm_v1,
        vlm_review_enabled=False,
        renderer=lambda doc: _make_rendered(passed=False, issues=("text_overlap:2_pairs",)),
    )
    assert m4["status"] == "empty"
    assert not (folder / "visuals" / "slide-01.png").exists()
    assert (folder / "note.md").read_text(encoding="utf-8") == orig_md
    assert json.loads((folder / "result.json").read_text(encoding="utf-8"))["markdown"] == orig_md


def test_m2_stale_markdown_not_overwritten_and_unexpected_error_persists_internal_error(tmp_path):
    artifacts, task_id, folder, orig_md = _create_completed_task(tmp_path)
    orig_status = (folder / "status.json").read_bytes()

    # Concurrent modification of result.json during generation must NOT be overwritten
    edited_md = orig_md + "\n## 人工补充\n\n最新人工编辑内容。\n"

    def mutating_renderer(doc):
        (folder / "note.md").write_text(edited_md, encoding="utf-8")
        (folder / "result.json").write_text(
            json.dumps({"markdown": edited_md, "title": "产品架构评审"}, ensure_ascii=False),
            encoding="utf-8",
        )
        return _make_rendered(passed=True)

    m = generate_visual_slides_for_task(
        artifacts,
        "alice",
        task_id,
        llm_complete=lambda s, u: _plan_json(1) if "Available ## Headings" in u else "<div><h1>X</h1></div>",
        vlm_review_enabled=False,
        renderer=mutating_renderer,
    )
    assert m["status"] == "ready"
    assert (folder / "note.md").read_text(encoding="utf-8") == edited_md
    assert json.loads((folder / "result.json").read_text(encoding="utf-8"))["markdown"] == edited_md

    # Unexpected non-security crash degrades gracefully to status="failed", error_code="internal_error"
    artifacts2, task_id2, folder2, orig_md2 = _create_completed_task(tmp_path / "boom")
    orig_status2 = (folder2 / "status.json").read_bytes()

    def crashing_renderer(doc):
        raise ZeroDivisionError("secret=/private/path/token")

    m_fail = generate_visual_slides_for_task(
        artifacts2,
        "alice",
        task_id2,
        llm_complete=lambda s, u: _plan_json(1) if "Available ## Headings" in u else "<div><h1>X</h1></div>",
        vlm_review_enabled=False,
        renderer=crashing_renderer,
    )
    assert m_fail["status"] == "failed"
    assert m_fail["error_code"] == "internal_error"
    assert "secret=" not in (folder2 / "visuals" / "manifest.json").read_text(encoding="utf-8")
    assert (folder2 / "note.md").read_text(encoding="utf-8") == orig_md2
    assert (folder2 / "status.json").read_bytes() == orig_status2


def test_m3_default_callables_use_stream_for_cloud_and_verify_local_config_with_complete(tmp_path, monkeypatch):
    from app.config import settings
    from app.models.model_profile import ResolvedLLMConfig
    from app.services import llm_service as llm_mod
    from app.services import task_model_source as tms_mod
    from app.services import vilab_cloud_service as cloud_mod
    from app.services import visual_slide_service as svc

    # Cloud snapshot -> stream=True
    _, _, cloud_folder, _ = _create_completed_task(tmp_path / "cloud")
    (cloud_folder / tms_mod.SNAPSHOT_FILE).write_text(
        json.dumps({
            "version": 1,
            "owner": "alice",
            "mode": "cloud",
            "server_url": settings.vilab_server_url,
            "asr_model": "asr-1",
            "llm_model": "gpt-test",
            "needs_stt": True,
        }),
        encoding="utf-8",
    )
    captured_cloud_req: dict = {}

    def fake_cloud_request(self, user_id, method, path, **kwargs):
        captured_cloud_req.update(kwargs)
        return {"choices": [{"message": {"content": '{"slides": []}'}}]}

    monkeypatch.setattr(cloud_mod.VILabCloudService, "request", fake_cloud_request)
    cloud_llm, _, ctx_factory = svc._build_default_model_callables(cloud_folder, "alice", want_vlm=False)
    with ctx_factory():
        assert cloud_llm("sys", "usr") == '{"slides": []}'
    assert captured_cloud_req["json"]["stream"] is True

    # Local snapshot -> calls verify_local_config AND summarizer._complete(system_prompt=..., user_prompt=...)
    _, _, local_folder, _ = _create_completed_task(tmp_path / "local")
    cfg = ResolvedLLMConfig(provider="anthropic-compatible", base_url="http://127.0.0.1:8080", model_name="local-m", api_key="k")
    fp = tms_mod.config_fingerprint(cfg)
    (local_folder / tms_mod.SNAPSHOT_FILE).write_text(
        json.dumps({
            "version": 1,
            "owner": "alice",
            "mode": "local",
            "server_url": "",
            "asr_model": "",
            "llm_model": "",
            "local_llm_fingerprint": fp,
            "local_stt_fingerprint": "0" * 64,
            "needs_stt": False,
        }),
        encoding="utf-8",
    )
    verified = {"called": False}
    complete_args: dict = {}

    class FakeSummarizer:
        def _complete(self, *, system_prompt: str, user_prompt: str) -> str:
            complete_args["system_prompt"] = system_prompt
            complete_args["user_prompt"] = user_prompt
            return "local-ok"

    real_verify = tms_mod.verify_local_config

    def spy_verify(user_id, kind, config):
        verified["called"] = True
        return real_verify(user_id, kind, config)

    monkeypatch.setattr(tms_mod, "verify_local_config", spy_verify)
    monkeypatch.setattr(llm_mod.LLMService, "resolve_config", lambda self, **kw: cfg)
    monkeypatch.setattr(llm_mod.LLMService, "build_summarizer", staticmethod(lambda c: FakeSummarizer()))

    local_llm, _, local_ctx = svc._build_default_model_callables(local_folder, "alice", want_vlm=False)
    with local_ctx():
        assert local_llm("S", "U") == "local-ok"
    assert verified["called"] is True
    assert complete_args == {"system_prompt": "S", "user_prompt": "U"}

