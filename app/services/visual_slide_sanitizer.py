"""Fail-closed DOM allowlist HTML/SVG/CSS sanitizer for VINote visual slides.

Uses Python stdlib ``html.parser`` only (zero third-party dependencies).
Produces two strictly separated outputs:
- ``disk_html``: zero external or font URLs, strict ``default-src 'none'`` CSP.
- ``render_html``: identical body plus optional pinned synthetic font-face URLs
  (fulfilled in-memory by the offline CDP renderer from SHA-256-verified font bytes).
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
from html.parser import HTMLParser
import re

CANVAS_WIDTH = 1600
CANVAS_HEIGHT = 900
MAX_RAW_HTML_BYTES = 128 * 1024
MAX_DOM_NODES = 1500
MAX_NESTING_DEPTH = 32

BUNDLED_FONT_URL = "https://vinote-font.invalid/NotoSansSC-Regular.ttf"
BUNDLED_FONT_SHA256 = "028a6826552d2ab32eede9d4243381351382a154f974d96cac543fc571570407"
BUNDLED_FONT_BOLD_URL = "https://vinote-font.invalid/NotoSansSC-Bold.ttf"
BUNDLED_FONT_BOLD_SHA256 = "8c3394530d07b75cada0128a643801db834efd045d94bae5106612c68cc290b4"
BUNDLED_FONT_FAMILY = "VINoteNotoSansSC"

DISK_CSP = (
    "default-src 'none'; "
    "style-src 'unsafe-inline'; "
    "img-src 'none'; "
    "script-src 'none'; "
    "connect-src 'none'; "
    "font-src 'none'; "
    "media-src 'none'; "
    "object-src 'none'; "
    "frame-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)

RENDER_CSP_WITH_FONT = (
    "default-src 'none'; "
    "style-src 'unsafe-inline'; "
    "img-src 'none'; "
    "script-src 'none'; "
    "connect-src 'none'; "
    "font-src https://vinote-font.invalid; "
    "media-src 'none'; "
    "object-src 'none'; "
    "frame-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)

_HTML_VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})

_ALLOWED_HTML_TAGS = frozenset({
    "div", "section", "article", "header", "footer", "main", "aside", "nav",
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "span", "strong", "em", "b", "i",
    "u", "small", "mark", "code", "pre", "blockquote", "ul", "ol", "li",
    "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "caption", "colgroup", "col", "figure", "figcaption", "hr", "br",
    "sub", "sup", "time", "abbr",
})

_ALLOWED_SVG_TAGS = frozenset({
    "svg", "g", "defs", "symbol", "use", "path", "rect", "circle", "ellipse",
    "line", "polyline", "polygon", "text", "tspan", "textpath", "marker",
    "lineargradient", "radialgradient", "stop", "clippath", "pattern", "mask",
    "filter", "fedropshadow", "fegaussianblur", "feoffset", "feblend",
    "fecomposite", "fecolormatrix", "feflood", "femerge", "femergenode",
})

_ALLOWED_TAGS = _ALLOWED_HTML_TAGS | _ALLOWED_SVG_TAGS
_HREF_ALLOWED_TAGS = frozenset({"use", "textpath", "lineargradient", "radialgradient"})

_CANONICAL_SVG_TAGS = {
    "lineargradient": "linearGradient",
    "radialgradient": "radialGradient",
    "clippath": "clipPath",
    "textpath": "textPath",
    "fedropshadow": "feDropShadow",
    "fegaussianblur": "feGaussianBlur",
    "feoffset": "feOffset",
    "feblend": "feBlend",
    "fecomposite": "feComposite",
    "fecolormatrix": "feColorMatrix",
    "feflood": "feFlood",
    "femerge": "feMerge",
    "femergenode": "feMergeNode",
}

_CANONICAL_SVG_ATTRS = {
    "viewbox": "viewBox",
    "preserveaspectratio": "preserveAspectRatio",
    "gradientunits": "gradientUnits",
    "gradienttransform": "gradientTransform",
    "spreadmethod": "spreadMethod",
    "patternunits": "patternUnits",
    "patterncontentunits": "patternContentUnits",
    "patterntransform": "patternTransform",
    "markerwidth": "markerWidth",
    "markerheight": "markerHeight",
    "markerunits": "markerUnits",
    "refx": "refX",
    "refy": "refY",
    "textlength": "textLength",
    "lengthadjust": "lengthAdjust",
    "startoffset": "startOffset",
    "stddeviation": "stdDeviation",
}

_GLOBAL_ALLOWED_ATTRS = frozenset({
    "id", "class", "style", "role", "aria-label", "aria-hidden", "lang", "dir",
    "colspan", "rowspan", "scope", "headers",
})

_SVG_ALLOWED_ATTRS = frozenset({
    "xmlns", "viewbox", "width", "height", "x", "y", "x1", "y1", "x2", "y2",
    "cx", "cy", "r", "rx", "ry", "d", "points", "dx", "dy", "rotate",
    "textlength", "lengthadjust", "startoffset", "transform",
    "preserveaspectratio", "fill", "fill-opacity", "fill-rule",
    "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
    "stroke-dasharray", "stroke-dashoffset", "stroke-opacity",
    "stroke-miterlimit", "opacity", "color", "font-family", "font-size",
    "font-weight", "font-style", "letter-spacing", "text-anchor",
    "dominant-baseline", "alignment-baseline", "offset", "stop-color",
    "stop-opacity", "gradientunits", "gradienttransform", "spreadmethod",
    "patternunits", "patterncontentunits", "patterntransform",
    "clip-path", "clip-rule", "mask", "filter",
    "marker-start", "marker-mid", "marker-end",
    "markerwidth", "markerheight", "refx", "refy", "orient", "markerunits",
    "vector-effect", "shape-rendering", "paint-order",
    "stddeviation", "in", "in2", "result", "mode", "operator", "type",
    "values", "flood-color", "flood-opacity", "fx", "fy", "fr",
    "href", "xlink:href",
})

_SVG_PAINT_REF_ATTRS = frozenset({
    "fill", "stroke", "clip-path", "mask", "filter",
    "marker-start", "marker-mid", "marker-end",
})

_LOCAL_FRAGMENT_RE = re.compile(r"^#[A-Za-z_][A-Za-z0-9_-]{0,63}\Z")
_LOCAL_URL_CALL_RE = re.compile(
    r"^url\(\s*['\"]?(#[A-Za-z_][A-Za-z0-9_-]{0,63})['\"]?\s*\)\Z", re.IGNORECASE
)
_URL_TOKEN_RE = re.compile(r"url\s*\([^)]*\)", re.IGNORECASE)
_ID_ATTR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_:-]{0,63}\Z")
_CLASS_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")
_CSS_PROP_RE = re.compile(r"^(?:--[A-Za-z0-9_-]{1,64}|-?[a-z][a-z0-9-]{0,63})\Z")
_CSS_HEX_ESCAPE_RE = re.compile(r"\\[0-9a-fA-F]{1,6}[ \t\r\n\f]?")
_CSS_ANY_ESCAPE_RE = re.compile(r"\\([^\r\n\f])")
_CSS_COMMENT_RE = re.compile(r"/\*.*?(?:\*/|\Z)", re.DOTALL)

_FORBIDDEN_CSS_SUBSTRINGS = (
    "@import",
    "@font-face",
    "@charset",
    "@namespace",
    "@document",
    "expression(",
    "behavior",
    "-moz-binding",
    "javascript:",
    "vbscript:",
    "data:",
    "file:",
    "http:",
    "https:",
    "//",
    "image-set(",
    "src(",
    "cross-fade(",
)

_FORBIDDEN_CSS_PROPS = frozenset({"behavior", "-moz-binding"})

_FORBIDDEN_ATTR_SUBSTRINGS = (
    "javascript:",
    "vbscript:",
    "data:",
    "file:",
    "http://",
    "https://",
    "//",
)

_SAFE_BLOCK_AT_RULES = frozenset({"@media", "@supports", "@layer"})


class SlideSanitizationError(ValueError):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class SanitizedSlideDoc:
    disk_html: str
    render_html: str
    visible_text_chars: int
    html_sha256: str


def _unescape_css(text: str) -> str:
    def _hex_sub(match: re.Match[str]) -> str:
        raw_hex = match.group(0)[1:].strip()
        try:
            codepoint = int(raw_hex, 16)
        except ValueError:
            return ""
        if 0 < codepoint <= 0x10FFFF:
            return chr(codepoint)
        return ""

    decoded = _CSS_HEX_ESCAPE_RE.sub(_hex_sub, text)
    return _CSS_ANY_ESCAPE_RE.sub(r"\1", decoded)


def _has_balanced_css_quotes(text: str) -> bool:
    quote: str | None = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if quote is not None:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        i += 1
    return quote is None


def _has_forbidden_css_tokens(raw_text: str, *, allow_local_url: bool) -> bool:
    if "<" in raw_text or "\x00" in raw_text or "\\" in raw_text:
        return True
    if not _has_balanced_css_quotes(raw_text):
        return True
    unescaped = _unescape_css(raw_text)
    if "<" in unescaped:
        return True
    lowered = unescaped.lower()
    if any(token in lowered for token in _FORBIDDEN_CSS_SUBSTRINGS):
        return True
    if "url(" in lowered or re.search(r"\burl\s*\(", lowered):
        if not allow_local_url:
            return True
        matches = list(_URL_TOKEN_RE.finditer(unescaped))
        if not matches:
            return True
        for m in matches:
            if not _LOCAL_URL_CALL_RE.fullmatch(m.group(0).strip()):
                return True
        remainder = _URL_TOKEN_RE.sub("", unescaped).lower()
        if "url(" in remainder or re.search(r"\burl\s*\(", remainder):
            return True
    return False


def _normalize_local_urls(text: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        inner = _LOCAL_URL_CALL_RE.fullmatch(match.group(0).strip())
        if not inner:
            return ""
        return f"url({inner.group(1)})"

    return _URL_TOKEN_RE.sub(_repl, text)


def _split_css_declarations(block: str) -> list[str]:
    decls: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    paren_depth = 0
    i = 0
    n = len(block)
    while i < n:
        ch = block[i]
        if quote is not None:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                buf.append(block[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == "(":
            paren_depth += 1
            buf.append(ch)
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
            buf.append(ch)
        elif ch == ";" and paren_depth == 0:
            decls.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        decls.append("".join(buf))
    return decls


def _sanitize_css_declarations(block: str) -> str:
    clean: list[str] = []
    for raw_decl in _split_css_declarations(block):
        decl = raw_decl.strip()
        if not decl or ":" not in decl:
            continue
        prop, value = decl.split(":", 1)
        prop_clean = prop.strip().lower()
        val_clean = value.strip()
        if not prop_clean or not val_clean:
            continue
        if prop_clean in _FORBIDDEN_CSS_PROPS or not _CSS_PROP_RE.fullmatch(prop_clean):
            continue
        if _has_forbidden_css_tokens(prop, allow_local_url=False):
            continue
        if _has_forbidden_css_tokens(val_clean, allow_local_url=True):
            continue
        val_clean = _normalize_local_urls(val_clean)
        clean.append(f"{prop_clean}: {val_clean}")
    return "; ".join(clean)


def _sanitize_inline_style(style_text: str) -> str:
    stripped = _CSS_COMMENT_RE.sub("", style_text)
    return _sanitize_css_declarations(stripped)


def _sanitize_stylesheet(css_text: str, *, _depth: int = 0) -> str:
    if _depth > 4:
        return ""
    css = _CSS_COMMENT_RE.sub("", css_text)
    out: list[str] = []
    n = len(css)
    i = 0

    while i < n:
        while i < n and css[i].isspace():
            i += 1
        if i >= n:
            break

        # Read prelude until '{' or ';' (respecting quotes and parens)
        start = i
        quote: str | None = None
        paren_depth = 0
        terminator = ""
        while i < n:
            ch = css[i]
            if quote is not None:
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == quote:
                    quote = None
                i += 1
                continue
            if ch in ("'", '"'):
                quote = ch
                i += 1
                continue
            if ch == "(":
                paren_depth += 1
                i += 1
                continue
            if ch == ")":
                paren_depth = max(0, paren_depth - 1)
                i += 1
                continue
            if paren_depth == 0 and ch in ("{", ";"):
                terminator = ch
                break
            i += 1

        prelude = css[start:i].strip()
        if terminator == ";":
            # Statement at-rule (e.g. @import, @charset, @namespace) -> always drop
            i += 1
            continue
        if terminator != "{":
            break

        # Read matching '{ ... }' block
        i += 1
        body_start = i
        brace_depth = 1
        quote = None
        while i < n and brace_depth > 0:
            ch = css[i]
            if quote is not None:
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == quote:
                    quote = None
                i += 1
                continue
            if ch in ("'", '"'):
                quote = ch
                i += 1
                continue
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
                if brace_depth == 0:
                    break
            i += 1
        body = css[body_start:i]
        if i < n and css[i] == "}":
            i += 1

        if not prelude:
            continue

        unescaped_prelude = _unescape_css(prelude).strip()
        if unescaped_prelude.startswith("@"):
            rule_name = unescaped_prelude.split(None, 1)[0].split("(", 1)[0].lower()
            if rule_name not in _SAFE_BLOCK_AT_RULES:
                continue
            if _has_forbidden_css_tokens(prelude, allow_local_url=False):
                continue
            nested = _sanitize_stylesheet(body, _depth=_depth + 1)
            if nested:
                out.append(f"{prelude} {{\n{nested}\n}}")
            continue

        if _has_forbidden_css_tokens(prelude, allow_local_url=False) or "@" in unescaped_prelude:
            continue
        clean_decls = _sanitize_css_declarations(body)
        if clean_decls:
            out.append(f"{prelude} {{ {clean_decls} }}")

    return "\n".join(out)


def _sanitize_svg_paint_attr(value: str) -> str | None:
    val = value.strip()
    if not val or "\x00" in val or "\\" in val:
        return None
    lowered = val.lower()
    if any(tok in lowered for tok in _FORBIDDEN_ATTR_SUBSTRINGS):
        return None
    if "url(" in lowered or re.search(r"\burl\s*\(", lowered):
        match = _LOCAL_URL_CALL_RE.fullmatch(val)
        if not match:
            return None
        return f"url({match.group(1)})"
    return val


def _sanitize_attributes(tag: str, attrs: list[tuple[str, str | None]]) -> tuple[list[tuple[str, str]], bool]:
    """Return ``(sanitized_attrs, keep_element)``."""
    is_svg = tag in _ALLOWED_SVG_TAGS
    allowed = _GLOBAL_ALLOWED_ATTRS | (_SVG_ALLOWED_ATTRS if is_svg else frozenset())
    sanitized: list[tuple[str, str]] = []
    seen: set[str] = set()
    has_valid_href = False

    for raw_name, raw_val in attrs:
        if not raw_name:
            continue
        name = raw_name.strip().lower()
        if not name or name.startswith("on"):
            continue
        if name not in allowed:
            continue
        val = "" if raw_val is None else raw_val
        if "\x00" in val:
            continue

        if name == "xmlns":
            if tag != "svg" or val.strip() != "http://www.w3.org/2000/svg":
                continue
            out_name, out_val = "xmlns", "http://www.w3.org/2000/svg"
        elif name in ("href", "xlink:href"):
            if tag not in _HREF_ALLOWED_TAGS:
                continue
            cleaned = val.strip()
            if not _LOCAL_FRAGMENT_RE.fullmatch(cleaned):
                continue
            out_name, out_val = "href", cleaned
            has_valid_href = True
        elif name == "style":
            cleaned_style = _sanitize_inline_style(val)
            if not cleaned_style:
                continue
            out_name, out_val = "style", cleaned_style
        elif name == "id":
            cleaned_id = val.strip()
            if not _ID_ATTR_RE.fullmatch(cleaned_id):
                continue
            out_name, out_val = "id", cleaned_id
        elif name == "class":
            tokens = [tok for tok in val.split() if _CLASS_TOKEN_RE.fullmatch(tok)]
            if not tokens:
                continue
            out_name, out_val = "class", " ".join(tokens)
        elif name in _SVG_PAINT_REF_ATTRS and is_svg:
            paint = _sanitize_svg_paint_attr(val)
            if paint is None:
                continue
            out_name, out_val = name, paint
        else:
            lowered = val.lower()
            if any(tok in lowered for tok in _FORBIDDEN_ATTR_SUBSTRINGS):
                continue
            out_name = _CANONICAL_SVG_ATTRS.get(name, name) if is_svg else name
            out_val = val

        if out_name in seen:
            continue
        seen.add(out_name)
        sanitized.append((out_name, out_val))

    if tag == "use" and not has_valid_href:
        return [], False
    return sanitized, True


def _canonical_tag(tag: str) -> str:
    return _CANONICAL_SVG_TAGS.get(tag, tag)


def _format_open_tag(tag: str, attrs: list[tuple[str, str]], *, self_closing: bool = False) -> str:
    name = _canonical_tag(tag)
    if attrs:
        rendered_attrs = " ".join(
            f'{attr_name}="{html.escape(attr_val, quote=True)}"' for attr_name, attr_val in attrs
        )
        suffix = " />" if self_closing else ">"
        return f"<{name} {rendered_attrs}{suffix}"
    return f"<{name} />" if self_closing else f"<{name}>"


class _SlideHTMLSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # Stack frames: (tag_lower, mode) where mode in {"keep", "unwrap", "head", "style", "drop"}
        self._stack: list[tuple[str, str]] = []
        self._body_parts: list[str] = []
        self._style_chunks: list[str] = []
        self._current_style_buf: list[str] = []
        self.node_count = 0
        self.visible_text_chars = 0

    def _in_drop(self) -> bool:
        return any(mode == "drop" for _, mode in self._stack)

    def _in_head(self) -> bool:
        return bool(self._stack) and self._stack[-1][1] == "head"

    def _in_style(self) -> bool:
        return bool(self._stack) and self._stack[-1][1] == "style"

    def _in_defs(self) -> bool:
        return any(tag == "defs" and mode == "keep" for tag, mode in self._stack)

    def _kept_depth(self) -> int:
        return sum(1 for _, mode in self._stack if mode == "keep")

    def _count_node(self, *, adding_depth: bool) -> None:
        self.node_count += 1
        if self.node_count > MAX_DOM_NODES:
            raise SlideSanitizationError("too_many_nodes", f"DOM node count exceeds {MAX_DOM_NODES}")
        depth = self._kept_depth() + (1 if adding_depth else 0)
        if depth > MAX_NESTING_DEPTH:
            raise SlideSanitizationError("nesting_too_deep", f"DOM nesting depth exceeds {MAX_NESTING_DEPTH}")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if self._in_style():
            return
        if self._in_drop():
            if t not in _HTML_VOID_TAGS:
                self._stack.append((t, "drop"))
            return

        if t in ("html", "body"):
            self._stack.append((t, "unwrap"))
            return
        if t == "head":
            self._stack.append((t, "head"))
            return
        if t == "style":
            self._stack.append((t, "style"))
            self._current_style_buf = []
            return
        if self._in_head():
            if t not in _HTML_VOID_TAGS:
                self._stack.append((t, "drop"))
            return

        if t not in _ALLOWED_TAGS:
            if t not in _HTML_VOID_TAGS:
                self._stack.append((t, "drop"))
            return

        clean_attrs, keep = _sanitize_attributes(t, attrs)
        if not keep:
            if t not in _HTML_VOID_TAGS:
                self._stack.append((t, "drop"))
            return

        is_void = t in _HTML_VOID_TAGS
        self._count_node(adding_depth=not is_void)
        self._body_parts.append(_format_open_tag(t, clean_attrs, self_closing=False))
        if not is_void:
            self._stack.append((t, "keep"))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if self._in_style() or self._in_drop() or self._in_head():
            return
        if t in ("html", "head", "body", "style"):
            return
        if t not in _ALLOWED_TAGS:
            return
        clean_attrs, keep = _sanitize_attributes(t, attrs)
        if not keep:
            return
        self._count_node(adding_depth=True)
        is_svg = t in _ALLOWED_SVG_TAGS
        if is_svg or t in _HTML_VOID_TAGS:
            self._body_parts.append(_format_open_tag(t, clean_attrs, self_closing=is_svg))
        else:
            self._body_parts.append(f"{_format_open_tag(t, clean_attrs, self_closing=False)}</{_canonical_tag(t)}>")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in _HTML_VOID_TAGS:
            return
        idx = -1
        for pos in range(len(self._stack) - 1, -1, -1):
            if self._stack[pos][0] == t:
                idx = pos
                break
        if idx < 0:
            return
        while len(self._stack) > idx:
            popped_tag, mode = self._stack.pop()
            if mode == "style":
                raw_css = "".join(self._current_style_buf)
                self._current_style_buf = []
                sanitized_css = _sanitize_stylesheet(raw_css)
                if sanitized_css:
                    self._style_chunks.append(sanitized_css)
            elif mode == "keep":
                self._body_parts.append(f"</{_canonical_tag(popped_tag)}>")

    def handle_data(self, data: str) -> None:
        if not data:
            return
        if self._in_style():
            self._current_style_buf.append(data)
            return
        if self._in_drop() or self._in_head():
            return
        escaped = html.escape(data, quote=False)
        self._body_parts.append(escaped)
        if not self._in_defs():
            self.visible_text_chars += len("".join(data.split()))

    def handle_comment(self, data: str) -> None:
        return

    def handle_pi(self, data: str) -> None:
        return

    def handle_decl(self, decl: str) -> None:
        return

    def finalize(self) -> tuple[str, str]:
        self.close()
        while self._stack:
            popped_tag, mode = self._stack.pop()
            if mode == "style":
                raw_css = "".join(self._current_style_buf)
                self._current_style_buf = []
                sanitized_css = _sanitize_stylesheet(raw_css)
                if sanitized_css:
                    self._style_chunks.append(sanitized_css)
            elif mode == "keep":
                self._body_parts.append(f"</{_canonical_tag(popped_tag)}>")
        return "\n".join(self._style_chunks).strip(), "".join(self._body_parts).strip()


def _build_document(
    *,
    title: str,
    csp: str,
    base_css: str,
    slide_css: str,
    body_html: str,
) -> str:
    safe_title = html.escape(title.strip()[:120] if title else "VINote Visual Slide", quote=False)
    combined_css = "\n".join(part for part in (base_css, slide_css) if part)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">\n'
        f"<title>{safe_title}</title>\n"
        "<style>\n"
        f"{combined_css}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        f"{body_html}\n"
        "</body>\n"
        "</html>\n"
    )


def sanitize_slide_html(
    raw_html: str,
    *,
    title: str = "",
    include_bundled_font: bool = False,
    include_bold_font: bool = True,
) -> SanitizedSlideDoc:
    """Sanitize raw LLM-generated HTML/SVG into a self-contained 1600x900 slide doc."""
    if not isinstance(raw_html, str) or not raw_html.strip():
        raise SlideSanitizationError("empty_slide", "Slide HTML is empty")
    if "\x00" in raw_html:
        raise SlideSanitizationError("invalid_html", "Slide HTML contains null bytes")
    raw_bytes = raw_html.encode("utf-8")
    if len(raw_bytes) > MAX_RAW_HTML_BYTES:
        raise SlideSanitizationError("html_too_large", f"Slide HTML exceeds {MAX_RAW_HTML_BYTES} bytes")

    parser = _SlideHTMLSanitizer()
    parser.feed(raw_html)
    slide_css, body_html = parser.finalize()

    if parser.node_count == 0 or not body_html:
        raise SlideSanitizationError("empty_slide", "Slide has no allowed visual elements")

    disk_base_css = (
        f"html, body {{ margin: 0; padding: 0; width: {CANVAS_WIDTH}px; height: {CANVAS_HEIGHT}px; "
        "overflow: hidden; box-sizing: border-box; "
        "font-variant-numeric: tabular-nums; -webkit-font-smoothing: antialiased; "
        'font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", '
        '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }\n'
        "*, *::before, *::after { box-sizing: border-box; }"
    )
    disk_html = _build_document(
        title=title,
        csp=DISK_CSP,
        base_css=disk_base_css,
        slide_css=slide_css,
        body_html=body_html,
    )
    disk_bytes = disk_html.encode("utf-8")
    if len(disk_bytes) > MAX_RAW_HTML_BYTES:
        raise SlideSanitizationError("html_too_large", f"Sanitized HTML exceeds {MAX_RAW_HTML_BYTES} bytes")

    if include_bundled_font:
        if include_bold_font:
            font_faces_css = (
                "@font-face {\n"
                f'  font-family: "{BUNDLED_FONT_FAMILY}";\n'
                f'  src: url("{BUNDLED_FONT_URL}") format("truetype");\n'
                "  font-weight: 100 500;\n"
                "  font-style: normal;\n"
                "  font-display: block;\n"
                "}\n"
                "@font-face {\n"
                f'  font-family: "{BUNDLED_FONT_FAMILY}";\n'
                f'  src: url("{BUNDLED_FONT_BOLD_URL}") format("truetype");\n'
                "  font-weight: 600 900;\n"
                "  font-style: normal;\n"
                "  font-display: block;\n"
                "}\n"
            )
        else:
            # Static weight-400 fallback: declare exact weight 400 (never 100 900)
            # so Chromium can synthesize bold rather than flattening headings to 400.
            font_faces_css = (
                "@font-face {\n"
                f'  font-family: "{BUNDLED_FONT_FAMILY}";\n'
                f'  src: url("{BUNDLED_FONT_URL}") format("truetype");\n'
                "  font-weight: 400;\n"
                "  font-style: normal;\n"
                "  font-display: block;\n"
                "}\n"
            )
        render_base_css = (
            font_faces_css
            + f"html, body {{ margin: 0; padding: 0; width: {CANVAS_WIDTH}px; height: {CANVAS_HEIGHT}px; "
            "overflow: hidden; box-sizing: border-box; "
            "font-variant-numeric: tabular-nums; -webkit-font-smoothing: antialiased; "
            f'font-family: "{BUNDLED_FONT_FAMILY}", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", '
            '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }\n'
            "*, *::before, *::after { box-sizing: border-box; }"
        )
        render_html = _build_document(
            title=title,
            csp=RENDER_CSP_WITH_FONT,
            base_css=render_base_css,
            slide_css=slide_css,
            body_html=body_html,
        )
    else:
        render_html = disk_html

    return SanitizedSlideDoc(
        disk_html=disk_html,
        render_html=render_html,
        visible_text_chars=parser.visible_text_chars,
        html_sha256=hashlib.sha256(disk_bytes).hexdigest(),
    )
