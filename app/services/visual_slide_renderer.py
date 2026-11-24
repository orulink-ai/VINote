"""Offline headless Chrome CDP & optional sidecar renderer for VINote visual slides.

Security & operational guarantees:
- Loads sanitized HTML strictly via CDP ``Page.navigate("about:blank")`` +
  ``Page.setDocumentContent`` (never ``file://``).
- Runs Chrome with ``--host-resolver-rules=MAP * ~NOTFOUND``, ``--no-proxy-server``,
  ``--remote-debugging-address=127.0.0.1``, ``--remote-debugging-port=0``,
  ephemeral ``--user-data-dir``, and ``shell=False``.
- Connects via ``websockets.sync.client.connect(..., proxy=None)`` to a validated
  loopback ``ws://127.0.0.1:<port>/devtools/...`` endpoint only.
- Intercepts every network request via ``Fetch.enable`` and fails all requests with
  ``BlockedByClient`` except SHA-256-verified bundled font URLs referenced by the slide.
- Runs programmatic DOM & SVG geometry audit inside CDP and validates every PNG
  with Pillow (``DecompressionBombWarning`` as error, exact ``3200x1800``,
  ``n_frames == 1``, ``verify()`` + ``load()``, <= 10 MiB, blank-canvas rejection).
- Enforces single-render concurrency (``threading.Semaphore(1)``) and guaranteed
  subprocess termination + temp profile cleanup in ``finally``.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import queue
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit
import warnings

import httpx
from PIL import Image
import websockets.sync.client as websockets_sync

from app.services.visual_slide_sanitizer import (
    BUNDLED_FONT_BOLD_SHA256,
    BUNDLED_FONT_BOLD_URL,
    BUNDLED_FONT_SHA256,
    BUNDLED_FONT_URL,
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    SanitizedSlideDoc,
)

logger = logging.getLogger(__name__)

DEVICE_SCALE_FACTOR = 2
EXPECTED_WIDTH = CANVAS_WIDTH * DEVICE_SCALE_FACTOR   # 3200
EXPECTED_HEIGHT = CANVAS_HEIGHT * DEVICE_SCALE_FACTOR  # 1800
MAX_PNG_BYTES = 10 * 1024 * 1024                       # 10 MiB
MAX_SIDECAR_RESPONSE_BYTES = 12 * 1024 * 1024          # 12 MiB
MAX_BUNDLED_FONT_BYTES = 16 * 1024 * 1024              # 16 MiB
_WS_MAX_MESSAGE_BYTES = 32 * 1024 * 1024

_DEVTOOLS_WS_RE = re.compile(r"DevTools listening on (ws://[^\s]+)")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_RENDER_SEMAPHORE = threading.Semaphore(1)
_FONT_LOCK = threading.Lock()
_CACHED_FONTS: dict[str, tuple[bytes, str] | None] = {}

_GEOMETRY_AUDIT_JS = """
(() => {
  const VIEW_W = 1600;
  const VIEW_H = 900;
  const TOL = 2;
  const issues = [];

  const docEl = document.documentElement;
  const body = document.body;
  const scrollWidth = Math.max(docEl ? docEl.scrollWidth : 0, body ? body.scrollWidth : 0);
  const scrollHeight = Math.max(docEl ? docEl.scrollHeight : 0, body ? body.scrollHeight : 0);
  if (scrollWidth > VIEW_W + TOL) {
    issues.push(`viewport_overflow_x:${Math.round(scrollWidth)}>${VIEW_W}`);
  }
  if (scrollHeight > VIEW_H + TOL) {
    issues.push(`viewport_overflow_y:${Math.round(scrollHeight)}>${VIEW_H}`);
  }

  function isHidden(el) {
    let cur = el;
    while (cur && cur.nodeType === 1) {
      const tag = cur.tagName ? cur.tagName.toLowerCase() : "";
      if (tag === "defs" || tag === "style" || tag === "script" || tag === "head" || tag === "title") {
        return true;
      }
      const cs = window.getComputedStyle(cur);
      if (cs.display === "none" || cs.visibility === "hidden" || parseFloat(cs.opacity) === 0) {
        return true;
      }
      cur = cur.parentElement;
    }
    return false;
  }

  let overflowClipX = 0;
  let overflowClipY = 0;
  let elementOutOfBounds = 0;

  if (body) {
    const allEls = body.querySelectorAll("*");
    for (const el of allEls) {
      if (el instanceof SVGElement) continue;
      if (isHidden(el)) continue;
      const cs = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) continue;

      const clipModes = (v) => v === "hidden" || v === "clip" || v === "scroll" || v === "auto";
      if (clipModes(cs.overflowX) && el.clientWidth > 0) {
        if (el.scrollWidth > el.clientWidth + TOL) {
          overflowClipX += 1;
        }
      }
      if (clipModes(cs.overflowY) && el.clientHeight > 0) {
        if (el.scrollHeight > el.clientHeight + TOL) {
          overflowClipY += 1;
        }
      }
      if (
        rect.left < -TOL ||
        rect.top < -TOL ||
        rect.right > VIEW_W + TOL ||
        rect.bottom > VIEW_H + TOL
      ) {
        elementOutOfBounds += 1;
      }
    }
  }

  if (overflowClipX > 0) issues.push(`overflow_clip_x:${overflowClipX}`);
  if (overflowClipY > 0) issues.push(`overflow_clip_y:${overflowClipY}`);
  if (elementOutOfBounds > 0) issues.push(`element_out_of_bounds:${elementOutOfBounds}`);

  // Collect visible leaf text bounding boxes (HTML text nodes + SVG text/tspan)
  const textBoxes = [];
  let visibleTextChars = 0;
  let ownerSeq = 0;

  if (body) {
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const text = (node.nodeValue || "").replace(/\\s+/g, "");
      if (!text) continue;
      const parent = node.parentElement;
      if (!parent) continue;
      if (parent.closest("svg, defs, style, script, title")) continue;
      if (isHidden(parent)) continue;

      visibleTextChars += text.length;
      const range = document.createRange();
      range.selectNodeContents(node);
      const rects = range.getClientRects();
      const oid = ++ownerSeq;
      for (const r of rects) {
        if (r.width >= 2 && r.height >= 2) {
          textBoxes.push({
            owner: oid,
            left: r.left,
            top: r.top,
            right: r.right,
            bottom: r.bottom,
            width: r.width,
            height: r.height,
          });
        }
      }
    }
  }

  let svgOutOfBounds = 0;
  let svgTextOutOfSvg = 0;
  let svgTextClippedInRect = 0;

  const svgs = document.querySelectorAll("svg");
  for (const svg of svgs) {
    if (isHidden(svg)) continue;
    const svgRect = svg.getBoundingClientRect();
    if (svgRect.width <= 0 || svgRect.height <= 0) continue;
    if (
      svgRect.left < -TOL ||
      svgRect.top < -TOL ||
      svgRect.right > VIEW_W + TOL ||
      svgRect.bottom > VIEW_H + TOL
    ) {
      svgOutOfBounds += 1;
    }

    const svgArea = svgRect.width * svgRect.height;
    const candidateRects = [];
    for (const rEl of svg.querySelectorAll("rect")) {
      if (isHidden(rEl)) continue;
      const rr = rEl.getBoundingClientRect();
      if (rr.width < 12 || rr.height < 12) continue;
      if (svgArea > 0 && (rr.width * rr.height) / svgArea > 0.78) continue;
      candidateRects.push({ el: rEl, rect: rr, area: rr.width * rr.height });
    }

    for (const tEl of svg.querySelectorAll("text")) {
      if (isHidden(tEl)) continue;
      const rawText = (tEl.textContent || "").replace(/\\s+/g, "");
      if (!rawText) continue;
      visibleTextChars += rawText.length;

      const tRect = tEl.getBoundingClientRect();
      if (tRect.width >= 2 && tRect.height >= 2) {
        if (
          tRect.left < svgRect.left - TOL ||
          tRect.top < svgRect.top - TOL ||
          tRect.right > svgRect.right + TOL ||
          tRect.bottom > svgRect.bottom + TOL
        ) {
          svgTextOutOfSvg += 1;
        }

        // Check if this text sits inside a containing SVG <rect> node box
        const cx = (tRect.left + tRect.right) / 2;
        const cy = (tRect.top + tRect.bottom) / 2;
        let bestBox = null;
        for (const cand of candidateRects) {
          const b = cand.rect;
          if (cx >= b.left - 1 && cx <= b.right + 1 && cy >= b.top - 1 && cy <= b.bottom + 1) {
            if (!bestBox || cand.area < bestBox.area) {
              bestBox = cand;
            }
          }
        }
        if (bestBox) {
          const b = bestBox.rect;
          if (
            tRect.left < b.left - TOL ||
            tRect.right > b.right + TOL ||
            tRect.top < b.top - TOL ||
            tRect.bottom > b.bottom + TOL
          ) {
            svgTextClippedInRect += 1;
          }
        }
      }

      const tspans = Array.from(tEl.querySelectorAll("tspan")).filter(
        (sp) => ((sp.textContent || "").replace(/\\s+/g, "").length > 0) && !isHidden(sp)
      );
      const targets = tspans.length > 0 ? tspans : [tEl];
      for (const target of targets) {
        const r = target.getBoundingClientRect();
        if (r.width >= 2 && r.height >= 2) {
          textBoxes.push({
            owner: ++ownerSeq,
            left: r.left,
            top: r.top,
            right: r.right,
            bottom: r.bottom,
            width: r.width,
            height: r.height,
          });
        }
      }
    }
  }

  if (svgOutOfBounds > 0) issues.push(`svg_out_of_bounds:${svgOutOfBounds}`);
  if (svgTextOutOfSvg > 0) issues.push(`svg_text_out_of_svg:${svgTextOutOfSvg}`);
  if (svgTextClippedInRect > 0) issues.push(`svg_text_clipped_in_rect:${svgTextClippedInRect}`);

  let textOutOfBounds = 0;
  for (const box of textBoxes) {
    if (
      box.left < -TOL ||
      box.top < -TOL ||
      box.right > VIEW_W + TOL ||
      box.bottom > VIEW_H + TOL
    ) {
      textOutOfBounds += 1;
    }
  }
  if (textOutOfBounds > 0) issues.push(`text_out_of_bounds:${textOutOfBounds}`);

  let overlapPairs = 0;
  for (let i = 0; i < textBoxes.length; i++) {
    const a = textBoxes[i];
    const areaA = a.width * a.height;
    for (let j = i + 1; j < textBoxes.length; j++) {
      const b = textBoxes[j];
      if (a.owner === b.owner) continue;
      const iw = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      if (iw <= 3) continue;
      const ih = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (ih <= 3) continue;
      const minArea = Math.min(areaA, b.width * b.height);
      if (minArea > 0 && (iw * ih) / minArea > 0.12) {
        overlapPairs += 1;
      }
    }
  }
  if (overlapPairs > 0) issues.push(`text_overlap:${overlapPairs}_pairs`);
  if (visibleTextChars === 0) issues.push("no_visible_text");

  return {
    passed: issues.length === 0,
    issues,
    metrics: {
      scroll_width: Math.round(scrollWidth),
      scroll_height: Math.round(scrollHeight),
      overflow_clip_x: overflowClipX,
      overflow_clip_y: overflowClipY,
      element_out_of_bounds: elementOutOfBounds,
      text_out_of_bounds: textOutOfBounds,
      text_overlaps: overlapPairs,
      svg_out_of_bounds: svgOutOfBounds,
      svg_text_out_of_svg: svgTextOutOfSvg,
      svg_text_clipped_in_rect: svgTextClippedInRect,
      visible_text_chars: visibleTextChars,
    },
  };
})()
"""


class VisualRendererUnavailableError(RuntimeError):
    def __init__(self, code: str = "chrome_unavailable"):
        self.code = code
        super().__init__(code)


class VisualRenderError(RuntimeError):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class GeometryAudit:
    passed: bool
    issues: tuple[str, ...]
    metrics: dict[str, int | float]


@dataclass(frozen=True)
class RenderedSlide:
    png_bytes: bytes
    width: int
    height: int
    png_sha256: str
    geometry: GeometryAudit
    renderer_kind: Literal["chrome-cdp", "sidecar"]


def validate_renderer_url(url: str) -> str:
    """Validate optional VISUAL_RENDERER_URL (loopback HTTP or HTTPS, no userinfo/query/fragment)."""
    if not isinstance(url, str):
        raise ValueError("VISUAL_RENDERER_URL must be a string")
    cleaned = url.strip()
    if not cleaned or any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise ValueError("VISUAL_RENDERER_URL contains invalid characters")
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("VISUAL_RENDERER_URL must use http (loopback only) or https")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("VISUAL_RENDERER_URL must not contain userinfo and must have a valid host")
    if parsed.query or parsed.fragment:
        raise ValueError("VISUAL_RENDERER_URL must not include query parameters or fragments")
    if parsed.scheme == "http" and parsed.hostname.lower() not in _LOOPBACK_HOSTS:
        raise ValueError("Plain HTTP VISUAL_RENDERER_URL is restricted to loopback addresses only")
    return cleaned


def _validate_cdp_ws_url(ws_url: str) -> str:
    if not isinstance(ws_url, str) or not ws_url.strip():
        raise VisualRenderError("invalid_cdp_endpoint", "Empty CDP WebSocket URL")
    parsed = urlsplit(ws_url.strip())
    if (
        parsed.scheme != "ws"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or not (1 <= parsed.port <= 65535)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/devtools/")
    ):
        raise VisualRenderError("invalid_cdp_endpoint", "CDP endpoint must be ws://127.0.0.1:<port>/devtools/...")
    return ws_url.strip()


def validate_rendered_png(png_bytes: bytes) -> tuple[int, int, str]:
    """Validate PNG format, exact 3200x1800 size, single frame, decompression bombs, and non-blank content."""
    if not isinstance(png_bytes, (bytes, bytearray)) or not png_bytes:
        raise VisualRenderError("invalid_png", "Empty PNG bytes")
    data = bytes(png_bytes)
    if len(data) > MAX_PNG_BYTES:
        raise VisualRenderError("png_too_large", f"PNG size exceeds {MAX_PNG_BYTES} bytes")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as img:
                if img.format != "PNG":
                    raise VisualRenderError("invalid_png_format", f"Expected PNG, got {img.format}")
                width, height = img.size
                if (width, height) != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
                    raise VisualRenderError(
                        "invalid_png_dimensions",
                        f"Expected {EXPECTED_WIDTH}x{EXPECTED_HEIGHT}, got {width}x{height}",
                    )
                if getattr(img, "n_frames", 1) != 1:
                    raise VisualRenderError("invalid_png_frames", "Animated PNG is not permitted")
                img.verify()
            with Image.open(BytesIO(data)) as img:
                img.load()
                extrema = img.convert("RGB").getextrema()
                if all(lo == hi for lo, hi in extrema):
                    raise VisualRenderError("blank_canvas", "Rendered PNG is a solid single-color blank canvas")
    except VisualRenderError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise VisualRenderError("invalid_png", "PNG decode or decompression bomb check failed") from None

    return width, height, hashlib.sha256(data).hexdigest()


def _load_verified_font_entry(filename: str, expected_sha256: str) -> tuple[bytes, str] | None:
    """Load, SHA-256-verify, and cache (raw_bytes, base64_ascii) for a bundled font."""
    with _FONT_LOCK:
        if filename in _CACHED_FONTS:
            return _CACHED_FONTS[filename]
        font_path = Path(__file__).resolve().parent.parent / "resources" / "fonts" / filename
        loaded: tuple[bytes, str] | None = None
        try:
            before = font_path.lstat()
            if (
                stat.S_ISREG(before.st_mode)
                and not stat.S_ISLNK(before.st_mode)
                and before.st_nlink == 1
                and not getattr(font_path, "is_junction", lambda: False)()
                and (0 < before.st_size <= MAX_BUNDLED_FONT_BYTES)
            ):
                fd = os.open(
                    font_path,
                    os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
                )
                with os.fdopen(fd, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if (
                        stat.S_ISREG(opened.st_mode)
                        and opened.st_nlink == 1
                        and (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino)
                        and opened.st_size <= MAX_BUNDLED_FONT_BYTES
                    ):
                        data = stream.read(MAX_BUNDLED_FONT_BYTES + 1)
                        if len(data) <= MAX_BUNDLED_FONT_BYTES:
                            if hashlib.sha256(data).hexdigest() == expected_sha256:
                                loaded = (data, base64.b64encode(data).decode("ascii"))
                            else:
                                logger.warning("Bundled font %s SHA-256 mismatch; refusing to serve in CDP", filename)
        except OSError:
            loaded = None
        _CACHED_FONTS[filename] = loaded
        return loaded


def load_bundled_font_bytes() -> bytes | None:
    """Load and SHA-256-verify the bundled NotoSansSC-Regular.ttf font once."""
    entry = _load_verified_font_entry("NotoSansSC-Regular.ttf", BUNDLED_FONT_SHA256)
    return entry[0] if entry is not None else None


def load_bundled_bold_font_bytes() -> bytes | None:
    """Load and SHA-256-verify the bundled NotoSansSC-Bold.ttf font once."""
    entry = _load_verified_font_entry("NotoSansSC-Bold.ttf", BUNDLED_FONT_BOLD_SHA256)
    return entry[0] if entry is not None else None


def _resolve_cdp_bundled_fonts(render_html: str) -> dict[str, str]:
    """Return URL -> base64 map only for verified bundled fonts actually referenced by render_html."""
    bundled: dict[str, str] = {}
    if BUNDLED_FONT_URL in render_html:
        regular_bytes = load_bundled_font_bytes()
        if regular_bytes is not None:
            entry = _CACHED_FONTS.get("NotoSansSC-Regular.ttf")
            bundled[BUNDLED_FONT_URL] = (
                entry[1] if entry is not None and entry[0] == regular_bytes
                else base64.b64encode(regular_bytes).decode("ascii")
            )
    if BUNDLED_FONT_BOLD_URL in render_html:
        bold_bytes = load_bundled_bold_font_bytes()
        if bold_bytes is not None:
            entry = _CACHED_FONTS.get("NotoSansSC-Bold.ttf")
            bundled[BUNDLED_FONT_BOLD_URL] = (
                entry[1] if entry is not None and entry[0] == bold_bytes
                else base64.b64encode(bold_bytes).decode("ascii")
            )
    return bundled


def _is_executable_file(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def discover_chrome_binary(configured_path: str | None = None) -> Path | None:
    """Locate a local Chromium/Chrome/Edge executable for offline CDP rendering."""
    if configured_path is not None and configured_path.strip():
        candidate = Path(configured_path.strip())
        return candidate if _is_executable_file(candidate) else None

    mac_candidates = (
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    )
    for path in mac_candidates:
        if _is_executable_file(path):
            return path

    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "msedge"):
        found = shutil.which(name)
        if found:
            candidate = Path(found)
            if _is_executable_file(candidate):
                return candidate

    if os.name == "nt":
        win_candidates = (
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        )
        for path in win_candidates:
            if _is_executable_file(path):
                return path

    return None


def _parse_geometry_payload(raw: Any) -> GeometryAudit:
    if not isinstance(raw, dict):
        return GeometryAudit(passed=False, issues=("geometry_audit_failed",), metrics={})
    passed = bool(raw.get("passed", False))
    raw_issues = raw.get("issues", [])
    issues = tuple(str(item)[:160] for item in raw_issues[:32]) if isinstance(raw_issues, list) else ()
    raw_metrics = raw.get("metrics", {})
    metrics: dict[str, int | float] = {}
    if isinstance(raw_metrics, dict):
        for k, v in raw_metrics.items():
            if isinstance(k, str) and type(v) in (int, float):
                metrics[k] = v
    if issues:
        passed = False
    return GeometryAudit(passed=passed, issues=issues, metrics=metrics)


class _CDPSession:
    def __init__(self, ws: Any, *, bundled_fonts: Mapping[str, str] | None = None):
        self._ws = ws
        self._bundled_fonts = dict(bundled_fonts or {})
        self._next_id = 0
        self._ignored_ids: set[int] = set()
        self.blocked_requests = 0
        self.fulfilled_font_requests = 0

    def _next_cmd_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _handle_fetch_paused(self, msg: dict[str, Any]) -> None:
        params = msg.get("params") or {}
        req_id = params.get("requestId")
        req_url = (params.get("request") or {}).get("url", "")
        session_id = msg.get("sessionId")
        if not req_id:
            return

        cmd_id = self._next_cmd_id()
        self._ignored_ids.add(cmd_id)

        font_b64 = self._bundled_fonts.get(req_url)
        if font_b64 is not None:
            self.fulfilled_font_requests += 1
            payload: dict[str, Any] = {
                "id": cmd_id,
                "method": "Fetch.fulfillRequest",
                "params": {
                    "requestId": req_id,
                    "responseCode": 200,
                    "responseHeaders": [
                        {"name": "Content-Type", "value": "font/ttf"},
                        {"name": "Access-Control-Allow-Origin", "value": "*"},
                    ],
                    "body": font_b64,
                },
            }
        else:
            self.blocked_requests += 1
            payload = {
                "id": cmd_id,
                "method": "Fetch.failRequest",
                "params": {
                    "requestId": req_id,
                    "errorReason": "BlockedByClient",
                },
            }
        if session_id:
            payload["sessionId"] = session_id
        self._ws.send(json.dumps(payload))

    def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        deadline: float,
    ) -> dict[str, Any]:
        cmd_id = self._next_cmd_id()
        payload: dict[str, Any] = {"id": cmd_id, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        self._ws.send(json.dumps(payload))

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VisualRenderError("cdp_timeout", f"CDP timed out waiting for {method}")
            raw = self._ws.recv(timeout=remaining)
            msg = json.loads(raw)
            if msg.get("method") == "Fetch.requestPaused":
                self._handle_fetch_paused(msg)
                continue
            resp_id = msg.get("id")
            if resp_id in self._ignored_ids:
                self._ignored_ids.discard(resp_id)
                continue
            if resp_id == cmd_id:
                if "error" in msg:
                    raise VisualRenderError("cdp_command_error", f"CDP error in {method}")
                return msg.get("result") or {}


def _read_devtools_ws_url(proc: subprocess.Popen[bytes], *, deadline: float) -> str:
    line_queue: queue.Queue[bytes | None] = queue.Queue()

    def _reader() -> None:
        assert proc.stderr is not None
        try:
            while True:
                line = proc.stderr.readline()
                if not line:
                    break
                line_queue.put(line)
        except OSError:
            pass
        finally:
            line_queue.put(None)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise VisualRenderError("chrome_launch_timeout", "Timed out waiting for Chrome DevTools endpoint")
        try:
            line = line_queue.get(timeout=min(0.25, remaining))
        except queue.Empty:
            if proc.poll() is not None:
                raise VisualRenderError("chrome_launch_failed", "Chrome exited before exposing DevTools")
            continue
        if line is None:
            raise VisualRenderError("chrome_launch_failed", "Chrome stderr closed before exposing DevTools")
        text = line.decode("utf-8", errors="replace")
        match = _DEVTOOLS_WS_RE.search(text)
        if match:
            return _validate_cdp_ws_url(match.group(1))


def _terminate_process(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
    finally:
        if proc.stderr is not None:
            try:
                proc.stderr.close()
            except OSError:
                pass


def _render_via_chrome_cdp(
    sanitized: SanitizedSlideDoc,
    *,
    chrome_bin: Path,
    timeout_seconds: float,
) -> RenderedSlide:
    deadline = time.monotonic() + max(3.0, float(timeout_seconds))
    user_data_dir = tempfile.mkdtemp(prefix="vinote-slide-chrome-")
    proc: subprocess.Popen[bytes] | None = None

    allow_font = sanitized.render_html != sanitized.disk_html
    bundled_fonts = _resolve_cdp_bundled_fonts(sanitized.render_html) if allow_font else {}

    cmd = [
        str(chrome_bin),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--disable-translate",
        "--metrics-recording-only",
        "--mute-audio",
        "--safebrowsing-disable-auto-update",
        "--block-new-web-contents",
        "--no-proxy-server",
        "--host-resolver-rules=MAP * ~NOTFOUND",
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=0",
        f"--user-data-dir={user_data_dir}",
        f"--window-size={CANVAS_WIDTH},{CANVAS_HEIGHT}",
        "--hide-scrollbars",
        "about:blank",
    ]

    with _RENDER_SEMAPHORE:
        try:
            proc = subprocess.Popen(
                cmd,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            ws_url = _read_devtools_ws_url(proc, deadline=deadline)
            open_timeout = max(1.0, min(10.0, deadline - time.monotonic()))
            with websockets_sync.connect(
                ws_url,
                proxy=None,
                open_timeout=open_timeout,
                close_timeout=2.0,
                max_size=_WS_MAX_MESSAGE_BYTES,
            ) as ws:
                cdp = _CDPSession(ws, bundled_fonts=bundled_fonts)
                target = cdp.send("Target.createTarget", {"url": "about:blank"}, deadline=deadline)
                target_id = target.get("targetId")
                if not target_id:
                    raise VisualRenderError("cdp_target_failed", "Failed to create CDP page target")

                attached = cdp.send(
                    "Target.attachToTarget",
                    {"targetId": target_id, "flatten": True},
                    deadline=deadline,
                )
                session_id = attached.get("sessionId")
                if not session_id:
                    raise VisualRenderError("cdp_attach_failed", "Failed to attach CDP session")

                cdp.send("Page.enable", session_id=session_id, deadline=deadline)
                cdp.send("Runtime.enable", session_id=session_id, deadline=deadline)
                cdp.send(
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": CANVAS_WIDTH,
                        "height": CANVAS_HEIGHT,
                        "deviceScaleFactor": DEVICE_SCALE_FACTOR,
                        "mobile": False,
                    },
                    session_id=session_id,
                    deadline=deadline,
                )
                cdp.send(
                    "Fetch.enable",
                    {"patterns": [{"urlPattern": "*"}]},
                    session_id=session_id,
                    deadline=deadline,
                )
                nav = cdp.send("Page.navigate", {"url": "about:blank"}, session_id=session_id, deadline=deadline)
                frame_id = nav.get("frameId")
                if not frame_id:
                    tree = cdp.send("Page.getFrameTree", session_id=session_id, deadline=deadline)
                    frame_id = ((tree.get("frameTree") or {}).get("frame") or {}).get("id")
                if not frame_id:
                    raise VisualRenderError("cdp_frame_missing", "Could not resolve page frameId")

                cdp.send(
                    "Page.setDocumentContent",
                    {"frameId": frame_id, "html": sanitized.render_html},
                    session_id=session_id,
                    deadline=deadline,
                )
                cdp.send(
                    "Runtime.evaluate",
                    {
                        "expression": (
                            "(async () => {"
                            " if (document.fonts && document.fonts.ready) {"
                            "   await Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, 3000))]);"
                            " }"
                            " await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));"
                            " return true;"
                            "})()"
                        ),
                        "awaitPromise": True,
                        "returnByValue": True,
                    },
                    session_id=session_id,
                    deadline=deadline,
                )

                audit_resp = cdp.send(
                    "Runtime.evaluate",
                    {
                        "expression": _GEOMETRY_AUDIT_JS,
                        "returnByValue": True,
                    },
                    session_id=session_id,
                    deadline=deadline,
                )
                audit_val = (audit_resp.get("result") or {}).get("value")
                geometry = _parse_geometry_payload(audit_val)

                shot = cdp.send(
                    "Page.captureScreenshot",
                    {"format": "png", "captureBeyondViewport": False, "fromSurface": True},
                    session_id=session_id,
                    deadline=deadline,
                )
                b64_data = shot.get("data")
                if not isinstance(b64_data, str) or not b64_data:
                    raise VisualRenderError("screenshot_empty", "Chrome returned empty screenshot")
                try:
                    png_bytes = base64.b64decode(b64_data, validate=True)
                except ValueError:
                    raise VisualRenderError("invalid_png", "Chrome returned malformed base64 screenshot") from None
        except (VisualRenderError, VisualRendererUnavailableError):
            raise
        except Exception as exc:
            logger.warning("Chrome CDP render failed: kind=%s", type(exc).__name__)
            raise VisualRenderError("cdp_render_failed", f"Chrome CDP render failed ({type(exc).__name__})") from None
        finally:
            _terminate_process(proc)
            shutil.rmtree(user_data_dir, ignore_errors=True)

    width, height, sha = validate_rendered_png(png_bytes)
    return RenderedSlide(
        png_bytes=png_bytes,
        width=width,
        height=height,
        png_sha256=sha,
        geometry=geometry,
        renderer_kind="chrome-cdp",
    )


def _render_via_sidecar(
    sanitized: SanitizedSlideDoc,
    *,
    renderer_url: str,
    timeout_seconds: float,
) -> RenderedSlide:
    validated_url = validate_renderer_url(renderer_url)
    raw_body = bytearray()
    content_type = ""
    try:
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=timeout_seconds) as client:
            with client.stream(
                "POST",
                validated_url,
                json={
                    "html": sanitized.disk_html,
                    "width": CANVAS_WIDTH,
                    "height": CANVAS_HEIGHT,
                    "scale": DEVICE_SCALE_FACTOR,
                },
            ) as response:
                if response.status_code != 200:
                    raise VisualRenderError("sidecar_http_error", f"Sidecar returned HTTP {response.status_code}")
                content_type = (response.headers.get("content-type") or "").lower()
                for chunk in response.iter_bytes(chunk_size=65536):
                    if len(raw_body) + len(chunk) > MAX_SIDECAR_RESPONSE_BYTES:
                        raise VisualRenderError(
                            "sidecar_response_too_large",
                            f"Sidecar response exceeded {MAX_SIDECAR_RESPONSE_BYTES} bytes",
                        )
                    raw_body.extend(chunk)
    except VisualRenderError:
        raise
    except httpx.HTTPError as exc:
        logger.warning("Sidecar render transport failed: kind=%s", type(exc).__name__)
        raise VisualRenderError("sidecar_transport_error", "Sidecar transport failed") from None

    if "image/png" in content_type:
        png_bytes = bytes(raw_body)
        geometry = GeometryAudit(passed=True, issues=(), metrics={"visible_text_chars": sanitized.visible_text_chars})
    else:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
            b64_png = payload["png_base64"]
            if not isinstance(b64_png, str) or not b64_png:
                raise ValueError("missing png_base64")
            png_bytes = base64.b64decode(b64_png, validate=True)
            geometry = _parse_geometry_payload(payload.get("geometry")) if "geometry" in payload else GeometryAudit(
                passed=True, issues=(), metrics={"visible_text_chars": sanitized.visible_text_chars}
            )
        except (ValueError, KeyError, TypeError):
            raise VisualRenderError("sidecar_invalid_payload", "Invalid sidecar JSON payload") from None

    width, height, sha = validate_rendered_png(png_bytes)
    return RenderedSlide(
        png_bytes=png_bytes,
        width=width,
        height=height,
        png_sha256=sha,
        geometry=geometry,
        renderer_kind="sidecar",
    )


def render_slide_html(
    sanitized: SanitizedSlideDoc,
    *,
    timeout_seconds: float = 20.0,
    chrome_path: str | None = None,
    renderer_url: str | None = None,
) -> RenderedSlide:
    """Render a sanitized 1600x900 slide into a validated 3200x1800 PNG + geometry audit."""
    if renderer_url and renderer_url.strip():
        return _render_via_sidecar(
            sanitized,
            renderer_url=renderer_url.strip(),
            timeout_seconds=timeout_seconds,
        )

    chrome_bin = discover_chrome_binary(chrome_path)
    if chrome_bin is None:
        raise VisualRendererUnavailableError("chrome_unavailable")

    return _render_via_chrome_cdp(
        sanitized,
        chrome_bin=chrome_bin,
        timeout_seconds=timeout_seconds,
    )
