"""Public single-post X intake via the official oEmbed endpoint.

No cookies, login, script execution, thread expansion or media/link retrieval.
The caller retains the returned text checkpoint before summarization. The text
is untrusted source material, including author names and any instructions in it.
"""
from __future__ import annotations

import json
import re
import time

import httpx
from bs4 import BeautifulSoup

from app.services import bilibili_source_service as bilibili
from app.services.document_source_service import _public_target

INPUT_HOSTS = frozenset({'x.com', 'www.x.com', 'mobile.x.com',
                         'twitter.com', 'www.twitter.com', 'mobile.twitter.com'})
OEMBED_URL = 'https://publish.x.com/oembed'
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_POST_CHARS = 100000
_UNAVAILABLE = '暂时无法读取这条 X 帖子的公开正文。请复制正文或导出文件后导入；尚未开始总结。'
_INVALID = '请提供完整的 X / Twitter 单帖链接，例如 https://x.com/用户名/status/帖子编号。'


def _canonical(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise ValueError(_INVALID)
    try:
        parsed = httpx.URL(value)
        if (parsed.scheme != 'https' or parsed.host not in INPUT_HOSTS
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise ValueError(_INVALID)
        path = parsed.raw_path.split(b'?', 1)[0].decode('ascii')
        matched = re.fullmatch(r'/([A-Za-z0-9_]{1,15})/status/([1-9][0-9]{0,19})/?', path)
        if not matched:
            raise ValueError(_INVALID)
        handle, post_id = matched.groups()
        return f'https://x.com/{handle}/status/{post_id}', handle, post_id
    except (httpx.InvalidURL, UnicodeError):
        raise ValueError(_INVALID) from None


def is_twitter_url(url):
    """Pure strict classification; no DNS, I/O or response inference."""
    try:
        _canonical(url)
        return True
    except ValueError:
        return False


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError(_UNAVAILABLE)
    return min(15.0, remaining)


def _extract(body, canonical, handle, post_id):
    if not isinstance(body, dict) or not isinstance(body.get('html'), str):
        raise ValueError(_UNAVAILABLE)
    if _canonical(body.get('url'))[2] != post_id:
        raise ValueError(_UNAVAILABLE)
    author = body.get('author_name')
    if author is not None and (not isinstance(author, str) or len(author) > 500):
        raise ValueError(_UNAVAILABLE)
    author = ' '.join((author or '').split()) or '@' + handle
    soup = BeautifulSoup(body['html'], 'html.parser')
    for node in soup.select('script, style, iframe, noscript, template, form'):
        node.decompose()
    blocks = soup.select('blockquote.twitter-tweet')
    if len(blocks) != 1:
        raise ValueError(_UNAVAILABLE)
    block = blocks[0]
    # Require the embed itself to reference the requested post. Never treat an
    # unrelated login/error page or another embedded post as the source.
    matching_permalink = False
    for anchor in block.find_all('a', recursive=False):
        try:
            matching_permalink |= _canonical(anchor.get('href'))[2] == post_id
        except ValueError:
            pass
    if not matching_permalink:
        raise ValueError(_UNAVAILABLE)
    paragraphs = []
    for paragraph in block.find_all('p', recursive=False):
        for nested in paragraph.select('blockquote'):
            nested.decompose()
        for br in paragraph.find_all('br'):
            br.replace_with('\n')
        text = paragraph.get_text('', strip=False).strip()
        if text:
            paragraphs.append(text)
    text = '\n\n'.join(paragraphs)
    if not text or len(text) > MAX_POST_CHARS or '\x00' in text:
        raise ValueError(_UNAVAILABLE)
    # No minimum article length: a short post can be complete and useful.
    source = (f'来源：{canonical}\n作者：{author}\n'
        '读取范围：仅此公开单帖的嵌入正文；不含完整线程、外链页面、图片内容或视频。'
        '嵌入正文可能不包含长帖全部内容，不将其当作完整长文。\n\n原文：\n' + text)
    return f'{author} · X 帖子'[:200], source


def twitter_text(url):
    """Return (title, text); never execute scripts or follow embedded URLs."""
    canonical, handle, post_id = _canonical(url)
    deadline = time.monotonic() + 25
    try:
        # Integration requires Bilibili's opt-in to permit ONLY publish.x.com;
        # arbitrary source hosts never become resolver allowlist parameters.
        original, target = _public_target(OEMBED_URL, fake_dns_resolver=lambda host:
            bilibili._resolve_public_dns(host, deadline, allow_x_publish=True))
        with httpx.Client(timeout=_remaining(deadline), trust_env=False, follow_redirects=False) as client:
            with client.stream('GET', target,
                params={'url': canonical, 'omit_script': 'true', 'hide_thread': 'true'},
                headers={'Accept': 'application/json', 'Accept-Encoding': 'identity',
                         'Host': original.netloc.decode('ascii')},
                extensions={'sni_hostname': original.raw_host.decode('ascii')}) as response:
                if response.status_code != 200 or 'application/json' not in response.headers.get('content-type', '').lower():
                    raise ValueError(_UNAVAILABLE)
                raw = bytearray()
                for chunk in response.iter_bytes(8192):
                    _remaining(deadline)
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise ValueError(_UNAVAILABLE)
        return _extract(json.loads(raw), canonical, handle, post_id)
    except (ValueError, RecursionError, httpx.RequestError):
        # Do not expose provider bodies, tracking query values or DNS details.
        raise ValueError(_UNAVAILABLE) from None
