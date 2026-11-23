"""Adversarial security & functional tests for visual_slide_sanitizer."""
import hashlib
import pytest

from app.services.visual_slide_sanitizer import (
    BUNDLED_FONT_URL,
    DISK_CSP,
    MAX_DOM_NODES,
    MAX_NESTING_DEPTH,
    MAX_RAW_HTML_BYTES,
    SanitizedSlideDoc,
    SlideSanitizationError,
    sanitize_slide_html,
)


def test_preserves_rich_html_css_and_svg_with_local_fragments():
    raw = """
    <style>
      .canvas { width: 1600px; height: 900px; background: linear-gradient(135deg, #f8fafc, #eef2f7); display: flex; }
      .title { font-size: 32px; color: #0f172a; }
    </style>
    <div class="canvas" id="root-slide">
      <header><h1 class="title">架构演进与关键指标</h1></header>
      <svg viewBox="0 0 800 400" width="800" height="400" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="#1d4ed8" />
            <stop offset="100%" stop-color="#0ea5e9" />
          </linearGradient>
          <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto">
            <path d="M0,0 L8,3 L0,6 Z" fill="#1d4ed8" />
          </marker>
          <g id="icon-node"><circle cx="10" cy="10" r="8" fill="#0ea5e9" /></g>
        </defs>
        <rect x="20" y="20" width="200" height="80" rx="12" fill="url(#grad1)" />
        <line x1="220" y1="60" x2="360" y2="60" stroke="#1d4ed8" stroke-width="2" marker-end="url(#arrow)" />
        <use href="#icon-node" x="380" y="50" />
        <text x="40" y="68" fill="#ffffff" font-size="18">JoyInside 协议层</text>
      </svg>
    </div>
    """
    doc = sanitize_slide_html(raw, title="架构图", include_bundled_font=False)
    assert isinstance(doc, SanitizedSlideDoc)
    assert doc.disk_html == doc.render_html
    assert doc.html_sha256 == hashlib.sha256(doc.disk_html.encode("utf-8")).hexdigest()
    assert DISK_CSP in doc.disk_html
    assert BUNDLED_FONT_URL not in doc.disk_html
    assert "<linearGradient" in doc.disk_html
    assert 'fill="url(#grad1)"' in doc.disk_html
    assert 'marker-end="url(#arrow)"' in doc.disk_html
    assert 'href="#icon-node"' in doc.disk_html
    assert "架构演进与关键指标" in doc.disk_html
    assert "JoyInside 协议层" in doc.disk_html
    assert doc.visible_text_chars >= 15


def test_disk_html_has_no_font_url_while_render_html_pins_synthetic_font():
    raw = "<div class='slide'><h1>会议结论</h1><p>核心数据</p></div>"
    doc = sanitize_slide_html(raw, title="结论", include_bundled_font=True)
    assert BUNDLED_FONT_URL not in doc.disk_html
    assert "font-src 'none'" in doc.disk_html
    assert "@font-face" not in doc.disk_html
    assert BUNDLED_FONT_URL in doc.render_html
    assert "font-src https://vinote-font.invalid" in doc.render_html
    assert "@font-face" in doc.render_html
    assert doc.html_sha256 == hashlib.sha256(doc.disk_html.encode("utf-8")).hexdigest()


def test_unwraps_full_html_document_and_strips_head_meta_link_script():
    raw = """<!DOCTYPE html>
    <html>
    <head>
      <meta http-equiv="refresh" content="0;url=https://evil.invalid">
      <link rel="stylesheet" href="https://evil.invalid/a.css">
      <script>alert(1)</script>
      <title>Ignored Head Title</title>
      <style>.card { padding: 24px; background: #fff; }</style>
    </head>
    <body>
      <div class="card"><h1>真实内容</h1></div>
    </body>
    </html>"""
    doc = sanitize_slide_html(raw, title="Safe Title")
    assert "evil.invalid" not in doc.disk_html
    assert "refresh" not in doc.disk_html
    assert "<link" not in doc.disk_html
    assert "<script" not in doc.disk_html
    assert "alert(1)" not in doc.disk_html
    assert "Ignored Head Title" not in doc.disk_html
    assert "<title>Safe Title</title>" in doc.disk_html
    assert "真实内容" in doc.disk_html
    assert ".card" in doc.disk_html


@pytest.mark.parametrize(
    "payload,forbidden",
    [
        ("<div onclick='alert(1)' onload='fetch(1)'><h1>ok</h1></div>", "onclick"),
        ("<div onmouseover='evil()'><h1>ok</h1></div>", "onmouseover"),
        ("<div><h1>ok</h1><script>fetch('https://evil.invalid')</script></div>", "<script"),
        ("<div><h1>ok</h1><iframe src='https://evil.invalid'></iframe></div>", "<iframe"),
        ("<div><h1>ok</h1><img src='http://127.0.0.1:9999/leak.png'></div>", "<img"),
        ("<div><h1>ok</h1><svg><image href='https://evil.invalid/x.png'/></svg></div>", "evil.invalid"),
        ("<div><h1>ok</h1><svg><foreignObject><div>xss</div></foreignObject></svg></div>", "foreignObject"),
        ("<div><h1>ok</h1><object data='https://evil.invalid'></object></div>", "<object"),
        ("<div><h1>ok</h1><embed src='https://evil.invalid'></div>", "<embed"),
        ("<div><h1>ok</h1><form action='https://evil.invalid'><input><button>go</button></form></div>", "<form"),
        ("<div><h1>ok</h1><base href='https://evil.invalid/'></div>", "<base"),
        ("<div><h1>ok</h1><audio src='file:///etc/passwd'></audio><video src='http://x'></video></div>", "<audio"),
        ("<div><h1>ok</h1><canvas id='c'></canvas></div>", "<canvas"),
        ("<div><h1>ok</h1><svg><animate attributeName='x' to='10'/><set attributeName='y' to='1'/></svg></div>", "<animate"),
        ("<div><h1>ok</h1><!-- secret comment --><?xml-stylesheet href='http://evil.invalid'?></div>", "secret comment"),
    ],
)
def test_strips_dangerous_tags_handlers_comments_and_pis(payload, forbidden):
    doc = sanitize_slide_html(payload)
    assert forbidden.lower() not in doc.disk_html.lower()
    assert "evil.invalid" not in doc.disk_html.lower()
    assert "127.0.0.1" not in doc.disk_html
    assert "file://" not in doc.disk_html
    assert "ok" in doc.disk_html


def test_blocks_external_svg_use_and_paint_urls_but_keeps_local_ids():
    raw = """
    <div>
      <svg viewBox="0 0 200 200">
        <defs><circle id="dot" cx="5" cy="5" r="5" /></defs>
        <use href="https://evil.invalid/sprite.svg#x" />
        <use xlink:href="file:///etc/passwd#x" />
        <use href="#dot" />
        <rect x="0" y="0" width="10" height="10" fill="url(https://evil.invalid/#g)" stroke="url(data:image/svg+xml,...)" />
        <rect x="20" y="0" width="10" height="10" fill="url(#dot)" />
      </svg>
    </div>
    """
    doc = sanitize_slide_html(raw)
    assert "evil.invalid" not in doc.disk_html
    assert "file://" not in doc.disk_html
    assert "data:" not in doc.disk_html
    assert 'href="#dot"' in doc.disk_html
    assert 'fill="url(#dot)"' in doc.disk_html


@pytest.mark.parametrize(
    "bad_css",
    [
        "@import url('https://evil.invalid/a.css');",
        "@import 'https://evil.invalid/a.css';",
        "@font-face { font-family: X; src: url(https://evil.invalid/f.woff2); }",
        ".a { background: url(http://127.0.0.1:8000/leak); }",
        ".a { background: url(https://evil.invalid/leak.png); }",
        ".a { background: url(file:///etc/passwd); }",
        ".a { background: url(data:image/png;base64,AAAA); }",
        ".a { background: url(//evil.invalid/x.png); }",
        ".a { background: \\75\\72\\6c(https://evil.invalid/hex.png); }",
        ".a { background: \\000075rl('https://evil.invalid/hex2.png'); }",
        "@\\69mport 'https://evil.invalid/hex-import.css';",
        ".a { width: expression(alert(1)); }",
        ".a { behavior: url(xss.htc); }",
        ".a { -moz-binding: url(http://evil.invalid/xss.xml); }",
        ".a { background: url(javascript:alert(1)); }",
        ".a { background: image-set('https://evil.invalid/a.png' 1x); }",
    ],
)
def test_blocks_css_exfiltration_and_obfuscation_in_style_and_inline(bad_css):
    raw = f"<style>{bad_css}\n.safe {{ color: #111827; }}</style><div class='safe' style=\"background: \\75\\72\\6c(https://evil.invalid/inline); color: #0f172a;\">Safe Text</div>"
    doc = sanitize_slide_html(raw)
    lower = doc.disk_html.lower()
    assert "evil.invalid" not in lower
    assert "127.0.0.1" not in lower
    assert "file://" not in lower
    assert "@import" not in lower
    assert "@font-face" not in lower
    assert "expression(" not in lower
    assert "-moz-binding" not in lower
    assert "javascript:" not in lower
    assert "image-set(" not in lower
    assert "\\75" not in lower
    assert "color: #111827" in doc.disk_html or "color:#111827" in doc.disk_html
    assert "Safe Text" in doc.disk_html


def test_preserves_css_local_fragment_url():
    raw = "<style>.box { clip-path: url(#clip-box); color: #1e293b; }</style><div class='box'>Clipped</div>"
    doc = sanitize_slide_html(raw)
    assert "url(#clip-box)" in doc.disk_html


def test_enforces_size_node_count_and_nesting_depth_limits():
    oversized = "<div>" + ("a" * (MAX_RAW_HTML_BYTES + 10)) + "</div>"
    with pytest.raises(SlideSanitizationError) as exc_size:
        sanitize_slide_html(oversized)
    assert exc_size.value.code == "html_too_large"

    too_many = "<div>" + ("<span>x</span>" * (MAX_DOM_NODES + 5)) + "</div>"
    with pytest.raises(SlideSanitizationError) as exc_nodes:
        sanitize_slide_html(too_many)
    assert exc_nodes.value.code == "too_many_nodes"

    too_deep = ("<div>" * (MAX_NESTING_DEPTH + 2)) + "x" + ("</div>" * (MAX_NESTING_DEPTH + 2))
    with pytest.raises(SlideSanitizationError) as exc_depth:
        sanitize_slide_html(too_deep)
    assert exc_depth.value.code == "nesting_too_deep"


def test_rejects_empty_or_script_only_slide():
    with pytest.raises(SlideSanitizationError):
        sanitize_slide_html("   ")
    with pytest.raises(SlideSanitizationError):
        sanitize_slide_html("<script>alert(1)</script>")


def test_escapes_title_and_prevents_style_breakout():
    raw = "<style>.a { color: #000; } </style><script>alert(1)</script></style><div>OK</div>"
    doc = sanitize_slide_html(raw, title="A </title><script>alert(1)</script>")
    assert "<script>" not in doc.disk_html.lower()
    assert "&lt;/title&gt;" in doc.disk_html


def test_blocks_charref_obfuscated_urls_anchors_feimage_and_nonhex_css_escapes():
    raw = """
    <style>
      .a { background: \\u\\r\\l(https://evil.invalid/nonhex.png); color: #0f172a; }
    </style>
    <div style="&#98;&#97;&#99;&#107;&#103;&#114;&#111;&#117;&#110;&#100;: url(https://evil.invalid/charref.png);">
      <a href="javascript:alert(1)">dropped link</a>
      <svg viewBox="0 0 100 100">
        <filter id="f"><feImage href="https://evil.invalid/f.png" /></filter>
        <use href="&#104;&#116;&#116;&#112;&#115;://evil.invalid/s.svg#id" />
      </svg>
      <p>Clean Content</p>
    </div>
    """
    doc = sanitize_slide_html(raw)
    lower = doc.disk_html.lower()
    assert "evil.invalid" not in lower
    assert "javascript:" not in lower
    assert "<feimage" not in lower
    assert "<a " not in lower
    assert "Clean Content" in doc.disk_html


def test_s1_rejects_all_css_backslashes_and_handles_escaped_quotes_without_leak():
    raw = (
        '<style>'
        '.a { content: "\\\\"; } '
        '.b { content: "x\\"y; background: url(https://evil.invalid/a)"; color: #111827; } '
        '.c { color: #1d4ed8; }'
        '</style>'
        '<div class="c" style=\'content: "\\\\"; color: #0f172a;\'>Safe</div>'
    )
    doc = sanitize_slide_html(raw)
    assert "\\" not in doc.disk_html
    assert "evil.invalid" not in doc.disk_html.lower()
    assert ".c { color: #1d4ed8 }" in doc.disk_html
    assert "color: #0f172a" in doc.disk_html


def test_s2_non_void_self_closing_html_tags_emit_explicit_closing_tag():
    raw = '<div class="wrap"><div class="bar" /><span class="dot" /><br /><h1>Title</h1></div>'
    doc = sanitize_slide_html(raw)
    assert '<div class="bar"></div>' in doc.disk_html
    assert '<span class="dot"></span>' in doc.disk_html
    assert "<br>" in doc.disk_html
    assert "<h1>Title</h1>" in doc.disk_html


def test_dual_weight_bundled_font_emits_regular_and_bold_faces_with_graceful_fallback():
    from app.services.visual_slide_sanitizer import BUNDLED_FONT_BOLD_SHA256, BUNDLED_FONT_BOLD_URL

    assert len(BUNDLED_FONT_BOLD_SHA256) == 64
    raw = '<div class="slide"><h1>加粗标题</h1><p>正文内容 2026</p></div>'

    dual = sanitize_slide_html(raw, title="双字重", include_bundled_font=True, include_bold_font=True)
    assert BUNDLED_FONT_URL not in dual.disk_html
    assert BUNDLED_FONT_BOLD_URL not in dual.disk_html
    assert "font-src 'none'" in dual.disk_html
    assert "font-variant-numeric: tabular-nums" in dual.disk_html
    assert "-webkit-font-smoothing: antialiased" in dual.disk_html
    assert BUNDLED_FONT_URL in dual.render_html
    assert BUNDLED_FONT_BOLD_URL in dual.render_html
    assert "font-weight: 100 500;" in dual.render_html
    assert "font-weight: 600 900;" in dual.render_html
    assert "font-weight: 100 900;" not in dual.render_html

    fallback = sanitize_slide_html(raw, title="单字重兜底", include_bundled_font=True, include_bold_font=False)
    assert BUNDLED_FONT_URL in fallback.render_html
    assert BUNDLED_FONT_BOLD_URL not in fallback.render_html
    assert "font-weight: 400;" in fallback.render_html
    assert "font-weight: 100 900;" not in fallback.render_html



