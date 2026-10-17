"""Bounded source-to-text only: no model, task, receipt or persistent original."""
import hashlib
from pathlib import Path

from app.services.document_source_service import MAX_BYTES, MAX_TEXT, document_text, webpage_text

TEXT_EXTENSIONS = {'.txt', '.md', '.srt', '.vtt', '.json'}
DOCUMENT_EXTENSIONS = {'.pdf', '.docx'}


def result(title, text, source_type):
    text = text.strip()
    if not text or len(text) > MAX_TEXT or '\x00' in text:
        raise ValueError('未读取到有效正文或正文超过长度限制，请分段导入')
    title = ''.join(char for char in title if char >= ' ').strip()[:500] or '导入正文'
    return {'extraction_protocol': 1, 'title': title, 'text': text,
            'source_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'source_type': source_type}


def extract_url(url):
    title, text, kind = webpage_text(url, reject_media=True, include_source_type=True)
    return result(title, text, kind)


def extract_file(filename, data):
    name = Path((filename or '').replace('\\', '/')).name
    suffix = Path(name).suffix.lower()
    if not data or len(data) > MAX_BYTES:
        raise ValueError('来源文件必须非空且不超过20 MiB')
    if suffix in DOCUMENT_EXTENSIONS:
        text, kind = document_text(name, data), 'document'
    elif suffix in TEXT_EXTENSIONS:
        # Validate bounded Unicode before the existing subtitle/JSON parser.
        raw = data.decode('utf-8-sig')
        if len(raw) > MAX_TEXT or '\x00' in raw:
            raise ValueError('文字文件超过长度限制或格式无效')
        from app.routers.note import _build_transcript_from_upload
        text = _build_transcript_from_upload(name, raw.encode('utf-8')).full_text
        kind = 'transcript'
    else:
        raise ValueError('仅支持PDF、DOCX、TXT、MD、SRT、VTT或JSON；音视频请在设备处理')
    return result(Path(name).stem, text, kind)
