"""Real HTTPX/httpcore wire with fake DNS/TCP; no provider/model calls."""
import json
from pathlib import Path
import socket
import ssl

from httpcore._backends.sync import SyncBackend
import pytest

from app.services import bilibili_source_service as source

BV = "BV1Pyta66EDh"
URL = f"https://www.bilibili.com/video/{BV}?p=1"
CDN = "https://upos-test.bilivideo.com/audio.m4s?secret=not-for-errors"
MP4 = b"\x00\x00\x00\x18ftypM4A " + b"audio" * 10


def response(body=b"", status=200, kind="application/json", extra=""):
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    return (f"HTTP/1.1 {status} Test\r\nContent-Type: {kind}\r\n"
            f"Content-Length: {len(body)}\r\n{extra}\r\n").encode() + body


def view(**changes):
    data = {"bvid": BV, "aid": 123, "title": "测试视频", "pages": [
        {"page": 1, "cid": 456, "duration": 73, "part": "第一集"},
        {"page": 2, "cid": 457, "duration": 80, "part": "第二集"}]}
    data.update(changes)
    return response({"code": 0, "data": data})


def play(url=CDN, **changes):
    data = {"dash": {"audio": [{"baseUrl": url, "mimeType": "audio/mp4",
                                "codecs": "mp4a.40.2", "bandwidth": 64000}]}}
    data.update(changes)
    return response({"code": 0, "data": data})


@pytest.fixture
def wire(monkeypatch):
    state = {"replies": [], "dns": [], "connections": [], "tls": [], "requests": [],
             "answers": {}, "closed": 0}

    def dns(host, port, *args, **kwargs):
        state["dns"].append(host)
        if host == "8.8.8.8":
            addresses = [host]
        else:
            choices = state["answers"].get(host, [["8.8.8.8"]])
            addresses = choices.pop(0) if len(choices) > 1 else choices[0]
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))
                for ip in addresses]

    class Stream:
        def __init__(self, body):
            self.body = body

        def read(self, max_bytes, timeout=None):
            data, self.body = self.body[:max_bytes], self.body[max_bytes:]
            return data

        def write(self, data, timeout=None):
            state["requests"].append(bytes(data))

        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            state["tls"].append((server_hostname, ssl_context.check_hostname, ssl_context.verify_mode))
            return self

        def close(self):
            state["closed"] += 1

        def get_extra_info(self, info):
            return None

    def connect(_self, host, port, **kwargs):
        assert host == "8.8.8.8", "must connect to validated IP, never hostname"
        state["connections"].append((host, port))
        return Stream(state["replies"].pop(0))

    monkeypatch.setattr(source.httpx._client, "get_environment_proxies",
                        lambda: pytest.fail("must not consult environment proxies"))
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setattr(SyncBackend, "connect_tcp", connect)
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **kw: pytest.fail("real socket"))
    return state


@pytest.mark.parametrize("url", [URL, f"https://m.bilibili.com/video/{BV}/",
                                 "https://bilibili.com/video/av123?p=2", "https://b23.tv/abcDEF"])
def test_input_validation_never_resolves_or_fetches(wire, url):
    assert source.is_bilibili_url(url)
    assert source.validate_input(url)
    assert not wire["dns"] and not wire["requests"]


@pytest.mark.parametrize("url", [
    "https://bilibili.com.evil/video/" + BV, "https://evilbilibili.com/video/" + BV,
    "https://api.bilibili.com/video/" + BV, "http://www.bilibili.com/video/" + BV,
    "https://user:password@www.bilibili.com/video/" + BV,
    "https://www.bilibili.com:444/video/" + BV, "https://127.0.0.1/video/" + BV,
    "https://www.bilibili.com/bangumi/play/ep123", URL + "&p=2", URL.replace("p=1", "p=0"),
    URL.replace("p=1", "p=-1"), URL.replace("p=1", "p=1.5"),
    URL.replace(BV, "BVbad"), URL.replace("/video/", "/video%2F"),
    "https://b23.tv/test?p=1", "https://b23.tv/a/b", URL + "\n"])
def test_bad_inputs_fail_before_network(wire, url):
    with pytest.raises(source.BilibiliSourceError) as exc:
        source.validate_input(url)
    assert exc.value.code == "VIDEO_SOURCE_INVALID"
    assert not wire["requests"]


def test_full_real_http_stack_part_identity_no_credentials_and_atomic_file(wire, tmp_path, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    wire["replies"] = [view(), play(), response(MP4, kind="audio/mp4")]
    item = source.resolve(URL.replace("p=1", "p=2") + "&tracking=private")
    assert item.video_id == BV + "_p2" and item.cid == 457 and item.duration == 80
    assert item.canonical_url == URL.replace("p=1", "p=2")
    assert "第二集" in item.title
    path = source.download_audio(item, tmp_path / "source.m4a", max_bytes=len(MP4))
    assert path.read_bytes() == MP4
    assert list(tmp_path.iterdir()) == [path]
    assert item.source_identity == {"platform": "bilibili", "video_id": BV + "_p2",
                                    "aid": 123, "cid": 457, "page": 2}
    sent = b"".join(wire["requests"])
    assert b"cid=457" in sent and b"fnval=16" in sent
    assert b"Authorization:" not in sent and b"Cookie:" not in sent and b"tracking" not in sent
    assert b"Referer: https://www.bilibili.com/" in sent
    assert [entry[0] for entry in wire["tls"]] == ["api.bilibili.com"] * 2 + ["upos-test.bilivideo.com"]
    assert all(verify and mode == ssl.CERT_REQUIRED for _, verify, mode in wire["tls"])
    assert all(host == "8.8.8.8" for host, _ in wire["connections"])


def test_short_redirect_strips_tracking_and_cookies(wire):
    wire["replies"] = [response(status=302, extra=f"Location: {URL}\r\nSet-Cookie: private=secret\r\n"),
                        view(), play()]
    assert source.resolve("https://b23.tv/abc").canonical_url == URL
    assert len(wire["connections"]) == 3
    assert b"Cookie:" not in b"".join(wire["requests"])


@pytest.mark.parametrize("location", ["https://127.0.0.1/", "https://evil.example/",
                                       "http://www.bilibili.com/video/" + BV])
def test_short_redirect_cannot_leave_allowlist(wire, location):
    wire["replies"] = [response(status=302, extra=f"Location: {location}\r\n")]
    with pytest.raises(source.BilibiliSourceError):
        source.resolve("https://b23.tv/abc")
    assert len(wire["connections"]) == 1


def test_dns_rebinding_of_api_is_checked_on_each_hop(wire):
    wire["answers"]["api.bilibili.com"] = [["8.8.8.8"], ["127.0.0.1"]]
    wire["replies"] = [view()]
    with pytest.raises(source.BilibiliSourceError):
        source.resolve(URL)
    assert wire["connections"] == [("8.8.8.8", 443)]


@pytest.mark.parametrize("addresses", [["8.8.8.8", "10.0.0.1"], ["127.0.0.1"], ["169.254.169.254"]])
def test_private_cdn_answers_never_connect_or_leave_file(wire, tmp_path, addresses):
    wire["answers"]["upos-test.bilivideo.com"] = [addresses]
    with pytest.raises(source.BilibiliSourceError):
        source.download_audio(item(), tmp_path / "source.m4a")
    assert not wire["connections"] and not list(tmp_path.iterdir())


def item(url=CDN):
    return source.BilibiliSource(URL, "标题", BV + "_p1", 73, url, 1, 123, 456)


@pytest.mark.parametrize("status", [401, 403, 412, 429])
def test_blocked_http_fixed_safe_message_no_retry(wire, status):
    wire["replies"] = [response(b"private provider content", status=status, kind="text/html")]
    with pytest.raises(source.BilibiliSourceError) as exc:
        source.resolve(URL)
    assert exc.value.code == "VIDEO_SOURCE_BLOCKED"
    assert str(exc.value) == "B站暂时限制了视频读取，尚未开始转写，可稍后重试或导入原文件"
    assert len(wire["connections"]) == 1


@pytest.mark.parametrize("code", [-352, -412, -403, -101])
def test_provider_json_block_fixed_safe_message(wire, code):
    wire["replies"] = [response({"code": code, "message": CDN})]
    with pytest.raises(source.BilibiliSourceError) as exc:
        source.resolve(URL)
    assert exc.value.code == "VIDEO_SOURCE_BLOCKED" and "secret" not in str(exc.value)


@pytest.mark.parametrize("changes", [{"bvid": "BVxxxxxxxxxx"}, {"aid": False},
                                    {"pages": []}, {"pages": [{"page": 1, "cid": 0, "duration": 73}]},
                                    {"pages": [{"page": 1, "cid": 456, "duration": float("nan")}]},
                                    {"title": ""}])
def test_metadata_must_match_identity_and_part(wire, changes):
    wire["replies"] = [view(**changes)]
    with pytest.raises(source.BilibiliSourceError) as exc:
        source.resolve(URL)
    assert exc.value.code == "VIDEO_SOURCE_UNAVAILABLE"
    assert len(wire["connections"]) == 1


@pytest.mark.parametrize("url", ["https://evil.example/a", "https://bilivideo.com.evil/a",
                                 "http://upos-test.bilivideo.com/a", "https://127.0.0.1/a",
                                 "https://user:secret@upos-test.bilivideo.com/a"])
def test_download_rechecks_cdn_allowlist(wire, tmp_path, url):
    with pytest.raises(source.BilibiliSourceError):
        source.download_audio(item(url), tmp_path / "source.m4a")
    assert not wire["dns"] and not list(tmp_path.iterdir())


@pytest.mark.parametrize("reply,limit,code", [
    (response(MP4, kind="audio/mp4"), len(MP4) - 1, "VIDEO_SOURCE_LIMIT"),
    (response(b"<html>error</html>", kind="audio/mp4"), 100, "VIDEO_SOURCE_UNAVAILABLE"),
    (response(MP4, kind="text/html"), 100, "VIDEO_SOURCE_UNAVAILABLE"),
    (response(MP4, kind="audio/mp4", extra="Content-Encoding: gzip\r\n"), 100, "VIDEO_SOURCE_UNAVAILABLE"),
    (response(MP4[:-1], kind="audio/mp4").replace(b"Content-Length: 61", b"Content-Length: 62"), 100, "VIDEO_SOURCE_UNAVAILABLE"),
])
def test_bad_or_oversized_download_leaves_no_target_or_part(wire, tmp_path, reply, limit, code):
    wire["replies"] = [reply]
    with pytest.raises(source.BilibiliSourceError) as exc:
        source.download_audio(item(), tmp_path / "source.m4a", max_bytes=limit)
    assert exc.value.code == code
    assert not list(tmp_path.iterdir())


def test_chunked_download_limit_checked_without_content_length(wire, tmp_path):
    chunks = b"".join(f"{len(p):x}\r\n".encode() + p + b"\r\n" for p in [MP4[:20], MP4[20:]])
    wire["replies"] = [b"HTTP/1.1 200 OK\r\nContent-Type: audio/mp4\r\nTransfer-Encoding: chunked\r\n\r\n" + chunks + b"0\r\n\r\n"]
    with pytest.raises(source.BilibiliSourceError) as exc:
        source.download_audio(item(), tmp_path / "source.m4a", max_bytes=30)
    assert exc.value.code == "VIDEO_SOURCE_LIMIT" and not list(tmp_path.iterdir())


def test_cdn_redirect_revalidates_new_dns_and_never_transfers_cookie(wire, tmp_path):
    wire["replies"] = [response(status=302, extra="Location: https://next.acgvideo.com/a\r\nSet-Cookie: signed=private\r\n"),
                        response(MP4, kind="audio/mp4")]
    source.download_audio(item(), tmp_path / "source.m4a")
    assert [x[0] for x in wire["tls"]] == ["upos-test.bilivideo.com", "next.acgvideo.com"]
    assert b"Cookie:" not in b"".join(wire["requests"])


def test_deadline_expires_before_network(wire, monkeypatch, tmp_path):
    ticks = iter([0, 181])
    monkeypatch.setattr(source.time, "monotonic", lambda: next(ticks))
    with pytest.raises(source.BilibiliSourceError) as exc:
        source.download_audio(item(), tmp_path / "source.m4a")
    assert exc.value.code == "VIDEO_SOURCE_LIMIT" and not wire["connections"]
    assert not list(tmp_path.iterdir())


def test_existing_target_is_preserved_and_not_fetched(wire, tmp_path):
    target = tmp_path / "source.m4a"
    target.write_bytes(b"original")
    with pytest.raises(source.BilibiliSourceError):
        source.download_audio(item(), target)
    assert target.read_bytes() == b"original" and not wire["connections"]


def test_signed_url_absent_from_repr_and_identity():
    assert "secret" not in repr(item())
    assert "secret" not in json.dumps(item().source_identity)


def test_excessive_query_fields_are_safe_validation_error(wire):
    with pytest.raises(source.BilibiliSourceError) as exc:
        source.validate_input(URL + "&" + "&".join(f"x{i}=1" for i in range(101)))
    assert exc.value.code == "VIDEO_SOURCE_INVALID" and not wire["dns"]


def test_av_resolves_to_canonical_bv_identity(wire):
    wire["replies"] = [view(), play()]
    result = source.resolve("https://www.bilibili.com/video/av123?p=2")
    assert result.video_id == BV + "_p2" and result.cid == 457
    assert b"view?aid=123" in b"".join(wire["requests"])


def test_missing_part_is_not_silently_replaced(wire):
    wire["replies"] = [view()]
    with pytest.raises(source.BilibiliSourceError):
        source.resolve(URL.replace("p=1", "p=3"))
    assert len(wire["connections"]) == 1


@pytest.mark.parametrize("role", ["short", "audio", "api"])
def test_redirect_count_is_bounded(wire, tmp_path, role):
    url = {"short": "https://b23.tv/abc", "audio": CDN,
           "api": "https://api.bilibili.com/x/web-interface/view?bvid=" + BV}[role]
    wire["replies"] = [response(status=302, extra=f"Location: {url}\r\n")] * 5
    with pytest.raises(source.BilibiliSourceError) as exc:
        source._get(url, role, source.time.monotonic() + 60)
    assert exc.value.code == "VIDEO_SOURCE_UNAVAILABLE" and len(wire["connections"]) == 5


@pytest.mark.parametrize("raw", [b"{invalid", b"[]", b'{"code":false,"data":{}}',
                                  b'{"code":0,"data":[]}'])
def test_malformed_json_is_fixed_error_without_body_leak(wire, raw):
    wire["replies"] = [response(raw)]
    with pytest.raises(source.BilibiliSourceError) as exc:
        source.resolve(URL)
    assert exc.value.code == "VIDEO_SOURCE_UNAVAILABLE"


def test_json_length_limit_rejected_before_reading(wire):
    wire["replies"] = [b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2097153\r\n\r\n"]
    with pytest.raises(source.BilibiliSourceError) as exc:
        source.resolve(URL)
    assert exc.value.code == "VIDEO_SOURCE_LIMIT"


def test_network_failure_never_retries_or_leaks_signed_url(wire, tmp_path, monkeypatch):
    from httpcore import ConnectError
    attempted = []

    def fail(_self, host, port, **kwargs):
        attempted.append(host)
        raise ConnectError(CDN)

    monkeypatch.setattr(SyncBackend, "connect_tcp", fail)
    with pytest.raises(source.BilibiliSourceError) as exc:
        source.download_audio(item(), tmp_path / "source.m4a")
    assert exc.value.code == "VIDEO_SOURCE_UNAVAILABLE" and "secret" not in str(exc.value)
    assert attempted == ["8.8.8.8"] and not list(tmp_path.iterdir())


def test_concurrent_target_is_never_overwritten(wire, tmp_path, monkeypatch):
    wire["replies"] = [response(MP4, kind="audio/mp4")]
    target = tmp_path / "source.m4a"
    link = source.os.link

    def race(first, second):
        target.write_bytes(b"another writer")
        return link(first, second)

    monkeypatch.setattr(source.os, "link", race)
    with pytest.raises(FileExistsError):
        source.download_audio(item(), target)
    assert target.read_bytes() == b"another writer" and list(tmp_path.iterdir()) == [target]


def test_no_supported_audio_does_not_fallback_to_video_or_ytdlp(wire):
    wire["replies"] = [view(), play(dash={"video": [{"baseUrl": CDN}], "audio": []})]
    with pytest.raises(source.BilibiliSourceError) as exc:
        source.resolve(URL)
    assert exc.value.code == "VIDEO_SOURCE_UNAVAILABLE" and len(wire["connections"]) == 2
