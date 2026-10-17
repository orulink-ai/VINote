"""Bounded public-page and document extraction; never executes source markup."""
from io import BytesIO
import ipaddress
from pathlib import Path
import socket
from urllib.parse import urljoin, urlparse
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import httpx

MAX_BYTES = 20 * 1024 * 1024
MAX_TEXT = 600_000
MEDIA_HOSTS = ("bilibili.com", "b23.tv", "youtube.com", "youtu.be", "vimeo.com",
               "douyin.com", "ixigua.com", "tiktok.com")


def is_document_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return not (any(host == item or host.endswith("." + item) for item in MEDIA_HOSTS)
                or parsed.path.rstrip("/").endswith("/video")
                or Path(parsed.path).suffix.lower() in {".mp4", ".webm", ".m4a", ".mp3", ".mov", ".m3u8"})


def public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("请提供不含账号密码的 HTTP 或 HTTPS 公开链接")
    if parsed.port not in (None, 80, 443):
        raise ValueError("网页链接仅支持标准 HTTP/HTTPS 端口")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError:
        raise ValueError("找不到这个网站，请检查链接或网络后重试") from None
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("不支持本机、内网或保留地址，请使用公开网页")
    return url


def document_text(filename, data):
    if not data or len(data) > MAX_BYTES:
        raise ValueError("文档必须非空且不超过 20 MB")
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise ValueError("PDF 已加密，请先解锁后重新导入")
            if len(reader.pages) > 200:
                raise ValueError("PDF 超过 200 页，请分段导入")
            parts = []
            for index, page in enumerate(reader.pages):
                value = page.extract_text() or ""
                parts.append(f"【第 {index + 1} 页】\n{value}" if value.strip() else "")
                if sum(map(len, parts)) > MAX_TEXT:
                    raise ValueError("文档正文过长，请分段导入")
            text = "\n\n".join(part for part in parts if part)
        elif suffix == ".docx":
            with ZipFile(BytesIO(data)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > MAX_BYTES:
                    raise ValueError("Word 解压后过大，请分段导入")
                xml = archive.read(info)
            if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                raise ValueError("Word 文档结构不受支持，请另存为 DOCX 后重试")
            root = ET.fromstring(xml)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            text = "\n".join("".join(node.itertext()) for node in root.findall(".//w:p", ns))
        else:
            raise ValueError("请选择 PDF 或 Word DOCX；旧版 DOC 请先另存为 DOCX")
    except ValueError:
        raise
    except Exception as exc:
        # Parser errors must not expose uploaded content or file paths.
        raise ValueError("文档无法读取，可能已损坏；请重新导出 PDF 或 DOCX 后重试") from exc
    if not text.strip():
        raise ValueError("未读取到正文；扫描 PDF 暂不支持 OCR，请先转为可选中文字的 PDF")
    if len(text) > MAX_TEXT:
        raise ValueError("文档正文过长，请分段导入")
    return text


def webpage_text(url):
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
        for _ in range(6):
            public_url(url)
            try:
                with client.stream("GET", url, headers={"User-Agent": "VINote/1.0 (document reader)"}) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    if response.status_code in (401, 403):
                        raise ValueError("此网页需要登录或拒绝读取，请导出文件后导入")
                    if response.status_code >= 400:
                        raise ValueError(f"网页暂时无法读取（HTTP {response.status_code}），请检查链接后重试")
                    data = bytearray()
                    for chunk in response.iter_bytes(65536):
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise ValueError("网页或文档超过 20 MB，请下载并分段导入")
                    kind = response.headers.get("content-type", "").lower()
                    if "application/pdf" in kind or urlparse(url).path.lower().endswith(".pdf"):
                        return "PDF 文档", document_text("source.pdf", bytes(data))
                    if "wordprocessingml" in kind or urlparse(url).path.lower().endswith(".docx"):
                        return "Word 文档", document_text("source.docx", bytes(data))
                    if "html" not in kind:
                        raise ValueError("这个链接不是可读取的网页、PDF 或 Word 文档")
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(bytes(data), "html.parser")
                    title = soup.title.get_text(" ", strip=True) if soup.title else "网页笔记"
                    for node in soup.select("script,style,nav,header,footer,aside,form,iframe,noscript"):
                        node.decompose()
                    body = soup.select_one("article, main, [role=main], .entry-content, .post-content, [itemprop=articleBody], #content") or soup.body
                    text = body.get_text("\n", strip=True) if body else ""
                    if len(text) < 40:
                        raise ValueError("网页未提供可读取正文，可能依赖登录或动态加载；请导出文件再导入")
                    if len(text) > MAX_TEXT:
                        raise ValueError("网页正文过长，请分段保存后导入")
                    return title[:200], text
            except httpx.RequestError:
                raise ValueError("网页读取超时或连接失败，请检查网络后重试") from None
    raise ValueError("网页跳转过多，请复制最终页面链接")
