"""Anonymous, bounded Bilibili audio intake. No yt-dlp, cookies or credentials.

Resolved audio URLs are ephemeral capabilities: never persist or log them.
The caller supplies a trusted output path and runs these synchronous functions
in its worker thread. No transcription or model calls occur here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import parse_qs, urlencode, urljoin

import httpx

from app.services.document_source_service import _public_target

PAGE_HOSTS = frozenset({"www.bilibili.com", "bilibili.com", "m.bilibili.com"})
INPUT_HOSTS = PAGE_HOSTS | {"b23.tv"}
CDN_SUFFIXES = (".bilivideo.com", ".bilivideo.cn", ".acgvideo.com")
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_AUDIO_BYTES = 128 * 1024 * 1024
MAX_REDIRECTS = 4
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
_BV = re.compile(r"BV[0-9A-Za-z]{10}\Z")
_MESSAGES = {
    "VIDEO_SOURCE_BLOCKED": "B站暂时限制了视频读取，尚未开始转写，可稍后重试或导入原文件",
    "VIDEO_SOURCE_UNAVAILABLE": "暂时无法读取这个B站视频，尚未开始转写，请稍后重试或导入原文件",
    "VIDEO_SOURCE_LIMIT": "视频音频超过读取大小或时间限制，尚未开始转写，请导入原文件",
    "VIDEO_SOURCE_INVALID": "请提供有效的B站BV、av视频链接或b23短链接，并检查分P编号",
}


class BilibiliSourceError(ValueError):
    """Safe to display; never includes provider bodies, URLs or credentials."""

    def __init__(self, code: str):
        self.code = code if code in _MESSAGES else "VIDEO_SOURCE_UNAVAILABLE"
        super().__init__(_MESSAGES[self.code])


def _fail(code="VIDEO_SOURCE_INVALID"):
    raise BilibiliSourceError(code)


def _url(value):
    try:
        if not isinstance(value, str) or len(value) > 8192 or any(ord(c) < 33 for c in value):
            _fail()
        url = httpx.URL(value)
        if (url.scheme != "https" or url.username or url.password
                or url.port not in (None, 443) or not url.raw_host):
            _fail()
        return url
    except (httpx.InvalidURL, UnicodeError, ValueError):
        _fail()


def is_bilibili_url(url: str) -> bool:
    """Strict host/scheme check only; validate_input additionally checks path/p."""
    try:
        return _url(url).host in INPUT_HOSTS
    except BilibiliSourceError:
        return False


def validate_input(url: str) -> str:
    """Pure validation before any model/catalog/receipt work; no DNS or I/O."""
    parsed = _url(url)
    if parsed.host not in INPUT_HOSTS:
        _fail()
    # Match raw ASCII paths, never percent-encoded separators or identifiers.
    path = parsed.raw_path.split(b"?", 1)[0].decode("ascii")
    try:
        query = parse_qs(parsed.query.decode("ascii"), keep_blank_values=True, max_num_fields=100)
    except (ValueError, UnicodeError):
        _fail()
    pages = query.get("p", ["1"])
    if len(pages) != 1 or not re.fullmatch(r"[1-9][0-9]{0,3}", pages[0]):
        _fail()
    if parsed.host == "b23.tv":
        if not re.fullmatch(r"/[A-Za-z0-9]{1,32}/?", path) or "p" in query:
            _fail()
        return "https://b23.tv/" + path.strip("/")
    match = re.fullmatch(r"/video/(BV[0-9A-Za-z]{10}|av[1-9][0-9]{0,19})/?", path)
    if not match:
        _fail()
    return f"https://www.bilibili.com/video/{match[1]}?p={int(pages[0])}"


@dataclass(frozen=True)
class BilibiliSource:
    canonical_url: str
    title: str
    video_id: str
    duration: float
    audio_url: str = field(repr=False)
    page: int
    aid: int
    cid: int

    @property
    def source_identity(self) -> dict:
        return {"platform": "bilibili", "video_id": self.video_id,
                "aid": self.aid, "cid": self.cid, "page": self.page}


def _allowed(url, role):
    parsed = _url(url)
    host = parsed.host
    if role == "short":
        validate_input(url)
    elif role == "api":
        if host != "api.bilibili.com" or parsed.path not in {
                "/x/web-interface/view", "/x/player/playurl"}:
            _fail()
    elif role == "audio":
        if not any(host.endswith(suffix) and host != suffix[1:] for suffix in CDN_SUFFIXES):
            _fail()
    else:
        _fail()
    return parsed


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        _fail("VIDEO_SOURCE_LIMIT")
    return min(20.0, remaining)


def _get(url, role, deadline, *, sink=None, limit=MAX_JSON_BYTES):
    """One isolated HTTPX session per hop, pinned TCP IP with original Host/SNI."""
    for hop in range(MAX_REDIRECTS + 1):
        _allowed(url, role)
        if role == "short" and httpx.URL(url).host in PAGE_HOSTS:
            return validate_input(url)
        try:
            original, target = _public_target(url)
        except ValueError:
            # Includes DNS failure and nonpublic/mixed answers. A well-formed
            # source can become unavailable; never retry against its hostname.
            _fail("VIDEO_SOURCE_UNAVAILABLE")
        timeout = _remaining(deadline)
        headers = {"User-Agent": UA, "Referer": "https://www.bilibili.com/",
                   "Accept-Encoding": "identity", "Host": original.netloc.decode("ascii")}
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                with client.stream("GET", target, headers=headers,
                                   extensions={"sni_hostname": original.raw_host.decode("ascii")}) as response:
                    _remaining(deadline)
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location or hop == MAX_REDIRECTS:
                            _fail("VIDEO_SOURCE_UNAVAILABLE")
                        url = urljoin(str(original), location)
                        continue
                    if response.status_code in {401, 403, 412, 429}:
                        _fail("VIDEO_SOURCE_BLOCKED")
                    if response.status_code != 200:
                        _fail("VIDEO_SOURCE_UNAVAILABLE")
                    if role == "short":
                        _fail("VIDEO_SOURCE_UNAVAILABLE")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        _fail("VIDEO_SOURCE_UNAVAILABLE")
                    length = response.headers.get("content-length")
                    if length is not None:
                        if not re.fullmatch(r"[0-9]{1,12}", length):
                            _fail("VIDEO_SOURCE_UNAVAILABLE")
                        if int(length) > limit:
                            _fail("VIDEO_SOURCE_LIMIT")
                    kind = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if role == "api" and kind not in {"application/json", "text/json"}:
                        _fail("VIDEO_SOURCE_UNAVAILABLE")
                    if role == "audio" and kind not in {
                            "audio/mp4", "video/mp4", "application/octet-stream", "audio/x-m4a"}:
                        _fail("VIDEO_SOURCE_UNAVAILABLE")
                    data = bytearray()
                    count = 0
                    prefix = bytearray()
                    for chunk in response.iter_bytes(64 * 1024):
                        _remaining(deadline)
                        count += len(chunk)
                        if count > limit:
                            _fail("VIDEO_SOURCE_LIMIT")
                        if len(prefix) < 12:
                            prefix.extend(chunk[:12 - len(prefix)])
                        if sink is None:
                            data.extend(chunk)
                        else:
                            sink.write(chunk)
                    if not count or (length is not None and count != int(length)):
                        _fail("VIDEO_SOURCE_UNAVAILABLE")
                    if role == "audio" and (len(prefix) < 12 or prefix[4:8] != b"ftyp"):
                        _fail("VIDEO_SOURCE_UNAVAILABLE")
                    return bytes(data) if sink is None else count
        except httpx.RequestError:
            _fail("VIDEO_SOURCE_UNAVAILABLE")
    _fail("VIDEO_SOURCE_UNAVAILABLE")


def _json(url, deadline):
    raw = _get(url, "api", deadline)
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        _fail("VIDEO_SOURCE_UNAVAILABLE")
    if not isinstance(body, dict):
        _fail("VIDEO_SOURCE_UNAVAILABLE")
    if body.get("code") in {-352, -412, -403, -101}:
        _fail("VIDEO_SOURCE_BLOCKED")
    if type(body.get("code")) is not int or body["code"] != 0 or not isinstance(body.get("data"), dict):
        _fail("VIDEO_SOURCE_UNAVAILABLE")
    return body["data"]


def _positive(value):
    return type(value) is int and 0 < value <= 10 ** 20


def resolve(url: str) -> BilibiliSource:
    """Resolve one anonymous part. Does not download audio or call any model."""
    normalized = validate_input(url)
    deadline = time.monotonic() + 60
    if httpx.URL(normalized).host == "b23.tv":
        normalized = _get(normalized, "short", deadline)
    parsed = httpx.URL(normalized)
    identifier = parsed.path.split("/")[-1]
    page = int(parse_qs(parsed.query.decode())["p"][0])
    query = {"bvid": identifier} if _BV.fullmatch(identifier) else {"aid": identifier[2:]}
    view = _json("https://api.bilibili.com/x/web-interface/view?" + urlencode(query), deadline)
    bvid, aid = view.get("bvid"), view.get("aid")
    pages = view.get("pages")
    if (not isinstance(bvid, str) or not _BV.fullmatch(bvid) or not _positive(aid)
            or (identifier.startswith("BV") and identifier != bvid)
            or (identifier.startswith("av") and int(identifier[2:]) != aid)
            or not isinstance(pages, list) or not 1 <= page <= len(pages)):
        _fail("VIDEO_SOURCE_UNAVAILABLE")
    part = pages[page - 1]
    if not isinstance(part, dict) or part.get("page") != page or not _positive(part.get("cid")):
        _fail("VIDEO_SOURCE_UNAVAILABLE")
    duration = part.get("duration")
    if (type(duration) not in (int, float) or not math.isfinite(duration)
            or not 0 < duration <= 24 * 60 * 60):
        _fail("VIDEO_SOURCE_UNAVAILABLE")
    title = view.get("title")
    if not isinstance(title, str) or not title.strip():
        _fail("VIDEO_SOURCE_UNAVAILABLE")
    if len(pages) > 1 and isinstance(part.get("part"), str):
        title += " — " + part["part"]
    title = "".join(c for c in title if ord(c) >= 32)[:300].strip()
    play = _json("https://api.bilibili.com/x/player/playurl?" + urlencode({
        "bvid": bvid, "cid": part["cid"], "fnval": 16, "fnver": 0, "qn": 16}), deadline)
    if play.get("is_preview") or play.get("need_vip"):
        _fail("VIDEO_SOURCE_BLOCKED")
    dash = play.get("dash")
    tracks = dash.get("audio") if isinstance(dash, dict) else None
    if not isinstance(tracks, list):
        _fail("VIDEO_SOURCE_UNAVAILABLE")
    # AAC MP4 only; avoid manifests, external playlists, DRM or codec guessing.
    tracks = [item for item in tracks if isinstance(item, dict)
              and item.get("mimeType", item.get("mime_type")) == "audio/mp4"
              and str(item.get("codecs", "")).startswith("mp4a.")
              and type(item.get("bandwidth")) is int and item["bandwidth"] > 0]
    if not tracks:
        _fail("VIDEO_SOURCE_UNAVAILABLE")
    audio = min(tracks, key=lambda item: item["bandwidth"])
    audio_url = audio.get("baseUrl") or audio.get("base_url")
    _allowed(audio_url, "audio")
    return BilibiliSource(f"https://www.bilibili.com/video/{bvid}?p={page}", title,
                          f"{bvid}_p{page}", float(duration), audio_url, page, aid, part["cid"])


def download_audio(source: BilibiliSource, target: str | Path,
                   max_bytes: int = MAX_AUDIO_BYTES) -> Path:
    """Stream to an exclusive temporary file, publish only a complete MP4 body.

    target belongs to the caller, never derived from a remote title. Existing
    files are never overwritten. Signed URLs are never included in errors.
    """
    if type(max_bytes) is not int or not 0 < max_bytes <= 512 * 1024 * 1024:
        _fail("VIDEO_SOURCE_LIMIT")
    _allowed(source.audio_url, "audio")
    target = Path(target)
    if target.exists() or target.is_symlink():
        _fail("VIDEO_SOURCE_INVALID")
    descriptor, temporary = tempfile.mkstemp(prefix=".bilibili-", suffix=".part", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            _get(source.audio_url, "audio", time.monotonic() + 180, sink=stream, limit=max_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        # link is atomic and refuses concurrent targets (unlike replace).
        os.link(temporary, target)
        return target
    finally:
        Path(temporary).unlink(missing_ok=True)
