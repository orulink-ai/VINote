"""Unit & real headless Chrome integration tests for visual_slide_renderer."""
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
import json
from pathlib import Path
import threading

from PIL import Image, ImageDraw
import pytest

from app.services.visual_slide_sanitizer import (
    BUNDLED_FONT_URL,
    SanitizedSlideDoc,
    sanitize_slide_html,
)
from app.services.visual_slide_renderer import (
    EXPECTED_HEIGHT,
    EXPECTED_WIDTH,
    MAX_PNG_BYTES,
    RenderedSlide,
    VisualRenderError,
    VisualRendererUnavailableError,
    _validate_cdp_ws_url,
    discover_chrome_binary,
    render_slide_html,
    validate_rendered_png,
    validate_renderer_url,
)


def _make_valid_png(*, blank: bool = False, size=(EXPECTED_WIDTH, EXPECTED_HEIGHT)) -> bytes:
    img = Image.new("RGB", size, (248, 250, 252))
    if not blank:
        draw = ImageDraw.Draw(img)
        draw.rectangle([100, 100, 600, 300], fill=(29, 78, 216))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# URL, CDP endpoint & Pillow validation unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "good_url",
    [
        "http://127.0.0.1:9300/render",
        "http://localhost:9300/render",
        "http://[::1]:9300/render",
        "https://slides-renderer.internal.example/render",
    ],
)
def test_validate_renderer_url_accepts_loopback_http_and_https(good_url):
    assert validate_renderer_url(good_url) == good_url


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://192.168.1.50:9300/render",
        "http://169.254.169.254/latest/meta-data",
        "http://user:pass@127.0.0.1:9300/render",
        "https://user@renderer.example/render",
        "file:///etc/passwd",
        "ftp://127.0.0.1/render",
        "http://127.0.0.1:9300/render?next=http://evil",
        "http://127.0.0.1:9300/render#frag",
        "not-a-url",
    ],
)
def test_validate_renderer_url_rejects_ssrf_and_invalid_urls(bad_url):
    with pytest.raises(ValueError):
        validate_renderer_url(bad_url)


def test_validate_cdp_ws_url_strictly_requires_loopback_devtools():
    good = "ws://127.0.0.1:54321/devtools/browser/abc-123"
    assert _validate_cdp_ws_url(good) == good
    for bad in (
        "ws://evil.invalid:9222/devtools/browser/abc",
        "ws://192.168.1.10:9222/devtools/browser/abc",
        "wss://127.0.0.1:9222/devtools/browser/abc",
        "ws://user@127.0.0.1:9222/devtools/browser/abc",
        "ws://127.0.0.1:9222/not-devtools",
        "http://127.0.0.1:9222/devtools/browser/abc",
    ):
        with pytest.raises(VisualRenderError):
            _validate_cdp_ws_url(bad)


def test_validate_rendered_png_checks_dimensions_blank_bomb_and_size(monkeypatch):
    good = _make_valid_png()
    w, h, sha = validate_rendered_png(good)
    assert (w, h) == (3200, 1800)
    assert len(sha) == 64

    # Wrong dimensions
    with pytest.raises(VisualRenderError) as exc_dim:
        validate_rendered_png(_make_valid_png(size=(1600, 900)))
    assert exc_dim.value.code == "invalid_png_dimensions"

    # Blank solid-color canvas
    with pytest.raises(VisualRenderError) as exc_blank:
        validate_rendered_png(_make_valid_png(blank=True))
    assert exc_blank.value.code == "blank_canvas"

    # Non-PNG (JPEG)
    jpg_buf = BytesIO()
    Image.new("RGB", (3200, 1800), (10, 20, 30)).save(jpg_buf, format="JPEG")
    with pytest.raises(VisualRenderError):
        validate_rendered_png(jpg_buf.getvalue())

    # Oversized bytes
    with pytest.raises(VisualRenderError) as exc_big:
        validate_rendered_png(b"\x89PNG" + b"\x00" * (MAX_PNG_BYTES + 1))
    assert exc_big.value.code == "png_too_large"

    # DecompressionBombWarning treated as error
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(VisualRenderError):
        validate_rendered_png(good)


# ---------------------------------------------------------------------------
# Mocked CDP WebSocket tests
# ---------------------------------------------------------------------------


def test_cdp_uses_proxy_none_blocks_network_fulfills_pinned_font_and_cleans_up(monkeypatch, tmp_path):
    from app.services import visual_slide_renderer as mod

    fake_chrome = tmp_path / "chrome"
    fake_chrome.write_text("#!/bin/sh\n")
    fake_chrome.chmod(0o755)
    monkeypatch.setattr(mod, "discover_chrome_binary", lambda configured_path=None: fake_chrome)
    monkeypatch.setattr(mod, "load_bundled_font_bytes", lambda: b"FAKE_FONT_BYTES")

    valid_png = _make_valid_png()
    sent_commands: list[dict] = []
    connect_kwargs: dict = {}
    killed = {"terminated": False, "killed": False}
    created_dirs: list[Path] = []

    real_mkdtemp = mod.tempfile.mkdtemp

    def tracking_mkdtemp(*args, **kwargs):
        d = real_mkdtemp(*args, **kwargs)
        created_dirs.append(Path(d))
        return d

    monkeypatch.setattr(mod.tempfile, "mkdtemp", tracking_mkdtemp)

    class FakeStderr:
        def __init__(self):
            self._lines = [b"DevTools listening on ws://127.0.0.1:45678/devtools/browser/fake\n"]

        def readline(self):
            return self._lines.pop(0) if self._lines else b""

        def close(self):
            pass

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.stderr = FakeStderr()
            self._code = None

        def poll(self):
            return self._code

        def terminate(self):
            killed["terminated"] = True
            self._code = 0

        def wait(self, timeout=None):
            self._code = 0
            return 0

        def kill(self):
            killed["killed"] = True
            self._code = -9

    monkeypatch.setattr(mod.subprocess, "Popen", FakeProc)

    class FakeWS:
        def __init__(self):
            self._incoming: list[str] = []

        def send(self, raw):
            msg = json.loads(raw)
            sent_commands.append(msg)
            cmd_id = msg["id"]
            method = msg["method"]
            session = msg.get("sessionId")
            if method == "Target.createTarget":
                self._incoming.append(json.dumps({"id": cmd_id, "result": {"targetId": "T1"}}))
            elif method == "Target.attachToTarget":
                self._incoming.append(json.dumps({"id": cmd_id, "result": {"sessionId": "S1"}}))
            elif method == "Page.navigate":
                self._incoming.append(json.dumps({"id": cmd_id, "result": {"frameId": "F1"}}))
            elif method == "Page.setDocumentContent":
                # Emit three Fetch.requestPaused events before answering: evil https, file://, and pinned font!
                self._incoming.append(json.dumps({
                    "method": "Fetch.requestPaused",
                    "sessionId": session,
                    "params": {"requestId": "R-evil", "request": {"url": "https://evil.invalid/leak"}},
                }))
                self._incoming.append(json.dumps({
                    "method": "Fetch.requestPaused",
                    "sessionId": session,
                    "params": {"requestId": "R-file", "request": {"url": "file:///etc/passwd"}},
                }))
                self._incoming.append(json.dumps({
                    "method": "Fetch.requestPaused",
                    "sessionId": session,
                    "params": {"requestId": "R-font", "request": {"url": BUNDLED_FONT_URL}},
                }))
                self._incoming.append(json.dumps({"id": cmd_id, "result": {}}))
            elif method == "Runtime.evaluate":
                expr = msg["params"]["expression"]
                if "scrollWidth" in expr:
                    self._incoming.append(json.dumps({
                        "id": cmd_id,
                        "result": {"result": {"value": {"passed": True, "issues": [], "metrics": {"visible_text_chars": 40}}}},
                    }))
                else:
                    self._incoming.append(json.dumps({"id": cmd_id, "result": {"result": {"value": True}}}))
            elif method == "Page.captureScreenshot":
                self._incoming.append(json.dumps({
                    "id": cmd_id,
                    "result": {"data": base64.b64encode(valid_png).decode("ascii")},
                }))
            else:
                self._incoming.append(json.dumps({"id": cmd_id, "result": {}}))

        def recv(self, timeout=None):
            return self._incoming.pop(0)

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def fake_connect(uri, **kwargs):
        connect_kwargs["uri"] = uri
        connect_kwargs.update(kwargs)
        return FakeWS()

    monkeypatch.setattr(mod.websockets_sync, "connect", fake_connect)

    doc = sanitize_slide_html("<div><h1>测试标题</h1><p>内容</p></div>", include_bundled_font=True)
    result = render_slide_html(doc)

    assert connect_kwargs["proxy"] is None
    assert result.width == 3200 and result.height == 1800
    assert result.renderer_kind == "chrome-cdp"
    assert result.geometry.passed is True

    # Verify Fetch.failRequest blocked evil https & file://, and Fetch.fulfillRequest fulfilled pinned font
    failed_reqs = [c["params"] for c in sent_commands if c["method"] == "Fetch.failRequest"]
    fulfilled_reqs = [c["params"] for c in sent_commands if c["method"] == "Fetch.fulfillRequest"]
    assert {r["requestId"] for r in failed_reqs} == {"R-evil", "R-file"}
    assert all(r["errorReason"] == "BlockedByClient" for r in failed_reqs)
    assert len(fulfilled_reqs) == 1 and fulfilled_reqs[0]["requestId"] == "R-font"
    assert base64.b64decode(fulfilled_reqs[0]["body"]) == b"FAKE_FONT_BYTES"

    # Verify process terminated & ephemeral temp profile removed
    assert killed["terminated"] or killed["killed"]
    assert len(created_dirs) == 1 and not created_dirs[0].exists()


def test_cdp_kills_chrome_and_cleans_temp_dir_on_error(monkeypatch, tmp_path):
    from app.services import visual_slide_renderer as mod

    fake_chrome = tmp_path / "chrome"
    fake_chrome.write_text("#!/bin/sh\n")
    fake_chrome.chmod(0o755)
    monkeypatch.setattr(mod, "discover_chrome_binary", lambda configured_path=None: fake_chrome)

    created_dirs: list[Path] = []
    real_mkdtemp = mod.tempfile.mkdtemp
    monkeypatch.setattr(
        mod.tempfile,
        "mkdtemp",
        lambda *a, **kw: (created_dirs.append(Path(d := real_mkdtemp(*a, **kw))) or d),
    )

    state = {"killed": False}

    class HangingProc:
        def __init__(self, cmd, **kwargs):
            self.stderr = BytesIO(b"DevTools listening on ws://127.0.0.1:45679/devtools/browser/hang\n")

        def poll(self):
            return None

        def terminate(self):
            state["killed"] = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            state["killed"] = True

    monkeypatch.setattr(mod.subprocess, "Popen", HangingProc)
    monkeypatch.setattr(mod.websockets_sync, "connect", lambda *a, **kw: (_ for _ in ()).throw(TimeoutError("cdp boom")))

    doc = sanitize_slide_html("<div><h1>Crash Test</h1></div>")
    with pytest.raises(VisualRenderError):
        render_slide_html(doc)

    assert state["killed"] is True
    assert len(created_dirs) == 1 and not created_dirs[0].exists()


def test_missing_chrome_raises_unavailable_error(monkeypatch):
    from app.services import visual_slide_renderer as mod

    monkeypatch.setattr(mod, "discover_chrome_binary", lambda configured_path=None: None)
    doc = sanitize_slide_html("<div><h1>No Chrome</h1></div>")
    with pytest.raises(VisualRendererUnavailableError):
        render_slide_html(doc, chrome_path="", renderer_url="")


# ---------------------------------------------------------------------------
# Sidecar renderer unit tests
# ---------------------------------------------------------------------------


def test_sidecar_uses_trust_env_false_no_redirects_and_enforces_12mib_cap(monkeypatch):
    from app.services import visual_slide_renderer as mod

    valid_png = _make_valid_png()
    captured_client_kwargs: dict = {}

    class FakeStreamResp:
        def __init__(self, status_code=200, headers=None, chunks=None):
            self.status_code = status_code
            self.headers = headers or {"content-type": "application/json"}
            self._chunks = chunks or []

        def iter_bytes(self, chunk_size=65536):
            yield from self._chunks

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    payload = json.dumps({
        "png_base64": base64.b64encode(valid_png).decode("ascii"),
        "geometry": {"passed": True, "issues": [], "metrics": {"visible_text_chars": 12}},
    }).encode("utf-8")

    def make_fake_client(resp):
        class FakeClient:
            def __init__(self, **kwargs):
                captured_client_kwargs.clear()
                captured_client_kwargs.update(kwargs)

            def stream(self, method, url, **kwargs):
                return resp

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return FakeClient

    monkeypatch.setattr(mod.httpx, "Client", make_fake_client(FakeStreamResp(chunks=[payload])))
    captured_body: dict = {}

    class CapturingClient:
        def __init__(self, **kwargs):
            captured_client_kwargs.clear()
            captured_client_kwargs.update(kwargs)

        def stream(self, method, url, **kwargs):
            captured_body.clear()
            captured_body.update(kwargs.get("json") or {})
            return FakeStreamResp(chunks=[payload])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(mod.httpx, "Client", CapturingClient)
    doc = sanitize_slide_html("<div><h1>Sidecar OK</h1></div>", include_bundled_font=True)
    rendered = render_slide_html(doc, renderer_url="http://127.0.0.1:9300/render")
    assert captured_client_kwargs["trust_env"] is False
    assert captured_client_kwargs["follow_redirects"] is False
    assert captured_body["html"] == doc.disk_html
    assert BUNDLED_FONT_URL not in captured_body["html"]
    assert rendered.renderer_kind == "sidecar"
    assert rendered.width == 3200 and rendered.height == 1800

    # Invalid base64 rejected strictly (validate=True)
    bad_b64_payload = json.dumps({"png_base64": "not!valid!base64!!!"}).encode("utf-8")
    monkeypatch.setattr(mod.httpx, "Client", make_fake_client(FakeStreamResp(chunks=[bad_b64_payload])))
    with pytest.raises(VisualRenderError) as exc_b64:
        render_slide_html(doc, renderer_url="http://127.0.0.1:9300/render")
    assert exc_b64.value.code == "sidecar_invalid_payload"

    # Oversized stream (> 12 MiB) rejected before loading all memory
    huge_chunks = [b"x" * (1024 * 1024)] * 13
    monkeypatch.setattr(mod.httpx, "Client", make_fake_client(FakeStreamResp(chunks=huge_chunks)))
    with pytest.raises(VisualRenderError) as exc:
        render_slide_html(doc, renderer_url="http://127.0.0.1:9300/render")
    assert exc.value.code == "sidecar_response_too_large"


# ---------------------------------------------------------------------------
# Real headless Chrome integration tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(discover_chrome_binary() is None, reason="Headless Chrome binary not available")
def test_real_chrome_renders_valid_3200x1800_slide_and_passes_geometry():
    raw = """
    <style>
      .slide {
        width: 1600px; height: 900px; padding: 56px 64px;
        background: #f8fafc; display: flex; flex-direction: column; gap: 32px;
      }
      h1 { margin: 0; font-size: 36px; color: #0f172a; }
      .subtitle { margin: 8px 0 0; font-size: 18px; color: #475569; }
      .cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; }
      .card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 24px; }
      .card h2 { margin: 0 0 12px; font-size: 20px; color: #1d4ed8; }
      .card p { margin: 0; font-size: 15px; color: #334155; line-height: 1.5; }
    </style>
    <div class="slide">
      <header>
        <h1>VINote 离线可视化幻灯片架构</h1>
        <p class="subtitle">零外链、严格几何审计与高分辨率 16:9 渲染</p>
      </header>
      <section class="cards">
        <div class="card"><h2>安全消毒</h2><p>基于标准库 DOM 白名单，剥离脚本与外部资源。</p></div>
        <div class="card"><h2>几何校验</h2><p>实时检测溢出、裁切与文字重叠。</p></div>
        <div class="card"><h2>无损交付</h2><p>输出 3200×1800 高清 PNG，兼容飞书原生图文。</p></div>
      </section>
      <svg viewBox="0 0 1472 220" width="1472" height="220" xmlns="http://www.w3.org/2000/svg">
        <rect x="20" y="30" width="380" height="120" rx="14" fill="#eff6ff" stroke="#bfdbfe" stroke-width="2" />
        <text x="210" y="96" text-anchor="middle" font-size="20" font-weight="600" fill="#1e3a8a">Markdown 会议纪要</text>
        <line x1="400" y1="90" x2="520" y2="90" stroke="#1d4ed8" stroke-width="3" />
        <rect x="520" y="30" width="420" height="120" rx="14" fill="#f0fdfa" stroke="#99f6e4" stroke-width="2" />
        <text x="730" y="96" text-anchor="middle" font-size="20" font-weight="600" fill="#115e59">离线 Chrome CDP 渲染</text>
        <line x1="940" y1="90" x2="1060" y2="90" stroke="#0f766e" stroke-width="3" />
        <rect x="1060" y="30" width="380" height="120" rx="14" fill="#ffffff" stroke="#cbd5e1" stroke-width="2" />
        <text x="1250" y="96" text-anchor="middle" font-size="20" font-weight="600" fill="#0f172a">3200×1800 PNG 图解</text>
      </svg>
    </div>
    """
    doc = sanitize_slide_html(raw, title="架构", include_bundled_font=True)
    rendered = render_slide_html(doc)
    assert isinstance(rendered, RenderedSlide)
    assert rendered.width == 3200
    assert rendered.height == 1800
    assert rendered.renderer_kind == "chrome-cdp"
    assert rendered.geometry.passed is True, f"Expected geometry pass, got issues={rendered.geometry.issues}"


@pytest.mark.skipif(discover_chrome_binary() is None, reason="Headless Chrome binary not available")
def test_real_chrome_detects_overflow_and_svg_text_overlap():
    overflow_html = """
    <style>
      .tall { width: 1600px; height: 1150px; background: #ffffff; padding: 40px; }
      .bottom { margin-top: 980px; font-size: 28px; color: #0f172a; }
    </style>
    <div class="tall"><h1>顶部标题</h1><p class="bottom">超出底部边界的段落</p></div>
    """
    overflow_doc = sanitize_slide_html(overflow_html)
    overflow_rendered = render_slide_html(overflow_doc)
    assert overflow_rendered.geometry.passed is False
    assert any("overflow" in issue or "out_of_bounds" in issue for issue in overflow_rendered.geometry.issues)

    overlap_html = """
    <div style="width:1600px;height:900px;background:#f8fafc;padding:40px;">
      <svg viewBox="0 0 800 300" width="800" height="300">
        <rect x="40" y="40" width="120" height="50" fill="#eff6ff" stroke="#1d4ed8" />
        <text x="100" y="70" text-anchor="middle" font-size="24" fill="#0f172a">这是一段故意超出矩形边框很长很长的重叠文字</text>
        <text x="100" y="72" text-anchor="middle" font-size="24" fill="#dc2626">第二段故意完全重叠在同一坐标上的文字</text>
      </svg>
    </div>
    """
    overlap_doc = sanitize_slide_html(overlap_html)
    overlap_rendered = render_slide_html(overlap_doc)
    assert overlap_rendered.geometry.passed is False
    assert any("text_overlap" in issue for issue in overlap_rendered.geometry.issues)
    assert any("svg_text_clipped_in_rect" in issue for issue in overlap_rendered.geometry.issues)

    # G1: overflow: auto / scroll inner clipping in a static PNG must also fail geometry
    scroll_clip_html = """
    <div style="width:1600px;height:900px;background:#f8fafc;padding:48px;">
      <div style="width:300px;height:60px;overflow:auto;background:#fff;border:1px solid #cbd5e1;padding:8px;">
        <p style="margin:0;font-size:18px;line-height:1.5;">
          这是一段故意放进 overflow:auto 容器里的很长很长的文字，静态 PNG 中底部会被裁切掉看不见。
        </p>
      </div>
    </div>
    """
    scroll_rendered = render_slide_html(sanitize_slide_html(scroll_clip_html))
    assert scroll_rendered.geometry.passed is False
    assert any("overflow_clip_y" in issue for issue in scroll_rendered.geometry.issues)


@pytest.mark.skipif(discover_chrome_binary() is None, reason="Headless Chrome binary not available")
def test_real_chrome_cdp_fetch_blocks_local_http_server_zero_hits():
    hits: list[str] = []

    class TrapHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"leaked")

        def log_message(self, fmt, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), TrapHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Deliberately bypass sanitizer to test defense-in-depth at the Chrome/CDP network layer!
        raw_html = (
            "<!DOCTYPE html><html><body style='margin:0;width:1600px;height:900px;background:#f8fafc;'>"
            f"<h1 style='color:#0f172a;padding:40px;'>Offline Trap Check</h1>"
            f"<img src='http://127.0.0.1:{port}/should-never-hit.png' width='200' height='200'>"
            "</body></html>"
        )
        doc = SanitizedSlideDoc(
            disk_html=raw_html,
            render_html=raw_html,
            visible_text_chars=18,
            html_sha256="0" * 64,
        )
        rendered = render_slide_html(doc)
        assert rendered.width == 3200 and rendered.height == 1800
        assert hits == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_load_bundled_bold_font_bytes_verifies_sha256_and_cdp_fulfills_both_weights():
    from app.services import visual_slide_renderer as mod
    from app.services.visual_slide_sanitizer import BUNDLED_FONT_BOLD_SHA256, BUNDLED_FONT_BOLD_URL

    # Real bundled NotoSansSC-Bold.ttf must load and match exact SHA-256
    bold_bytes = mod.load_bundled_bold_font_bytes()
    assert bold_bytes is not None
    import hashlib
    assert hashlib.sha256(bold_bytes).hexdigest() == BUNDLED_FONT_BOLD_SHA256

    # CDP session must fulfill Regular & Bold URLs while blocking unknown paths even on vinote-font.invalid
    sent: list[dict] = []

    class MiniWS:
        def send(self, raw):
            sent.append(json.loads(raw))

    cdp = mod._CDPSession(
        MiniWS(),
        bundled_fonts={
            BUNDLED_FONT_URL: base64.b64encode(b"REG_BYTES").decode("ascii"),
            BUNDLED_FONT_BOLD_URL: base64.b64encode(b"BOLD_BYTES").decode("ascii"),
        },
    )
    cdp._handle_fetch_paused({"params": {"requestId": "r1", "request": {"url": BUNDLED_FONT_URL}}})
    cdp._handle_fetch_paused({"params": {"requestId": "r2", "request": {"url": BUNDLED_FONT_BOLD_URL}}})
    cdp._handle_fetch_paused({"params": {"requestId": "r3", "request": {"url": "https://vinote-font.invalid/evil.ttf"}}})
    cdp._handle_fetch_paused({"params": {"requestId": "r4", "request": {"url": "https://evil.invalid/x"}}})

    fulfilled = {m["params"]["requestId"]: base64.b64decode(m["params"]["body"]) for m in sent if m["method"] == "Fetch.fulfillRequest"}
    failed = {m["params"]["requestId"] for m in sent if m["method"] == "Fetch.failRequest"}
    assert fulfilled == {"r1": b"REG_BYTES", "r2": b"BOLD_BYTES"}
    assert failed == {"r3", "r4"}


@pytest.mark.skipif(discover_chrome_binary() is None, reason="Headless Chrome binary not available")
def test_real_chrome_renders_visibly_distinct_bold_vs_regular_cjk_weights():
    def _dark_ink_pixels(weight: int) -> int:
        html = (
            f"<div style='width:1600px;height:900px;background:#ffffff;padding:80px;'>"
            f"<div style='font-size:72px;font-weight:{weight};color:#000000;'>终端定价刚性与架构演进</div>"
            f"</div>"
        )
        doc = sanitize_slide_html(html, include_bundled_font=True, include_bold_font=True)
        rendered = render_slide_html(doc)
        assert rendered.geometry.passed is True
        with Image.open(BytesIO(rendered.png_bytes)) as img:
            gray = img.convert("L")
            return sum(1 for px in gray.getdata() if px < 128)

    regular_ink = _dark_ink_pixels(400)
    bold_ink = _dark_ink_pixels(700)
    # True weight-700 Bold CJK strokes deposit noticeably more dark ink than weight-400 Regular
    assert regular_ink > 10_000
    assert bold_ink > int(regular_ink * 1.18), f"Expected bold ink ({bold_ink}) > 1.18x regular ({regular_ink})"

