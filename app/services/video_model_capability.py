"""Bounded image-input check for an exact account, model and service Origin."""
import base64
import hashlib
import io
import json
import math
import os
import re
import stat
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, ImageDraw

_LOCK = threading.Lock()
_TTL = 7 * 86400
_RECEIPT_PROTOCOL = 2  # Completed requires a checked, non-refusal stop response.


def _probe_answer(payload):
    """An HTTP success is not a complete compatibility result."""
    choices = payload.get('choices') if isinstance(payload, dict) else None
    if (not isinstance(choices, list) or len(choices) != 1
            or payload.get('error') is not None or not isinstance(choices[0], dict)
            or choices[0].get('finish_reason') != 'stop'):
        raise ValueError('画面能力核验结果尚未确认，未重复调用')
    message = choices[0].get('message')
    if (not isinstance(message, dict) or message.get('role') not in (None, 'assistant')
            or message.get('refusal') not in (None, '')
            or message.get('tool_calls') not in (None, [])
            or message.get('function_call') is not None):
        raise ValueError('画面能力核验结果尚未确认，未重复调用')
    answer = message.get('content')
    if not isinstance(answer, str) or not answer.strip() or len(answer) >= 2000:
        raise ValueError('画面能力核验结果尚未确认，未重复调用')
    if re.search(r"\b(?:cannot|can't|unable|unavailable|refus(?:e|al)|not able)\b", answer, re.I):
        raise ValueError('画面能力核验结果尚未确认，未重复调用')
    return answer


@contextmanager
def _capability_lock(path):
    if path.is_symlink():
        raise ValueError('画面能力核验记录异常')
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    locked = False
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b'\0')
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise ValueError('画面能力核验正在进行，未重复提交') from None
        yield
    finally:
        if locked:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _completed_receipt(path, identity):
    """Only a stable, fully validated terminal receipt is reusable without a lock.

    None means absent, never pending/unknown/expired. Invalid existing records
    must not authorize a new paid request or a rewrite of historical evidence.
    """
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    try:
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 4096
                or getattr(path, 'is_junction', lambda: False)()):
            raise ValueError('Invalid receipt')
        with path.open('rb') as handle:
            opened = os.fstat(handle.fileno())
            data = handle.read(4097)
            after = os.fstat(handle.fileno())
        stamp = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                              info.st_size, info.st_mtime_ns)
        if (len(data) > 4096 or stamp(before) != stamp(opened) or stamp(opened) != stamp(after)
                or stamp(path.lstat()) != stamp(before)):
            raise ValueError('Unstable receipt')
        saved = json.loads(data)
        if (not isinstance(saved, dict) or saved.get('identity') != identity
                or type(saved.get('protocol')) is not int or saved['protocol'] != _RECEIPT_PROTOCOL
                or saved.get('state') != 'completed' or type(saved.get('supported')) is not bool
                or saved.get('finish_reason') != 'stop'):
            raise ValueError('Invalid receipt')
        checked, now = saved.get('checked_at'), time.time()
        if (type(checked) not in (int, float) or not math.isfinite(checked)
                or checked > now or not 0 <= now - checked < _TTL):
            raise ValueError('Invalid or expired receipt')
        return saved['supported']
    except (OSError, KeyError, TypeError, ValueError):
        raise ValueError('画面能力核验记录不能确认，未重复调用') from None


def verify_image_input(owner: str, model: str, *, root: Path | None = None, cloud=None,
                       catalog_entry: dict | None = None) -> bool:
    """Never infer multimodal support from a model name or replay an unknown probe.

    Only a synthetic image is sent. Meeting media is not used for capability
    detection. The same selected model is used, without fallback.
    """
    from app.config import settings
    from app.services.vilab_cloud_service import VILabCloudService
    from app.services.video_evidence_service import supports_images
    cloud = cloud or VILabCloudService()
    entry = catalog_entry or next((row for row in cloud.models(owner)
                  if row.get('id') == model and row.get('modelType') == 'llm'), None)
    if entry is None or entry.get('id') != model or entry.get('modelType') != 'llm':
        raise ValueError('所选模型不在当前服务目录，未提交画面')
    capabilities = entry.get('capabilities') or {}
    vision = capabilities.get('vision')
    if (isinstance(vision, bool) or isinstance(vision, dict) and
            (isinstance(vision.get('supported'), bool) or vision.get('status') in {'supported', 'unsupported'})):
        return supports_images(capabilities)
    origin = cloud.status(owner)['server_url'].rstrip('/')
    identity = hashlib.sha256(json.dumps([owner, origin, model], ensure_ascii=False).encode()).hexdigest()
    folder = Path(root) if root is not None else Path(settings.data_dir) / 'image-input-checks'
    if folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)():
        raise ValueError('画面能力核验位置异常')
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{identity}.json'
    try:
        cached = _completed_receipt(path, identity)
    except (OSError, ValueError):
        # Only validated completed evidence bypasses the claim. All other
        # states still enter the original nonblocking lock and revalidate.
        cached = None
    if cached is not None:
        return cached
    with _LOCK, _capability_lock(folder / f'{identity}.lock'):
        cached = _completed_receipt(path, identity)
        if cached is not None:
            return cached
        record = {'protocol': _RECEIPT_PROTOCOL, 'identity': identity, 'state': 'pending', 'checked_at': time.time()}
        # Reserve before the paid request. Unknown transport outcomes remain pending.
        with path.open('x', encoding='utf-8') as handle:
            json.dump(record, handle)
            handle.flush()
            os.fsync(handle.fileno())
        picture = Image.new('RGB', (420, 180), 'white')
        draw = ImageDraw.Draw(picture)
        draw.ellipse((30, 30, 150, 150), fill=(220, 30, 30))
        draw.rectangle((260, 30, 380, 150), fill=(20, 70, 220))
        buffer = io.BytesIO()
        picture.save(buffer, format='PNG')
        image = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
        payload = cloud.request(owner, 'POST', '/openai/v1/chat/completions', timeout=180,
            json={'model': model, 'stream': False, 'messages': [{'role': 'user', 'content': [
                {'type': 'text', 'text': 'Describe only the color and shape on the LEFT and RIGHT of this image. Answer in English. Do not guess if image input is unavailable.'},
                {'type': 'image_url', 'image_url': {'url': image}},
            ]}]})
        answer = _probe_answer(payload)
        supported = bool(re.search(
            r'left.{0,40}red.{0,20}circle.{0,100}right.{0,40}blue.{0,20}square',
            answer, flags=re.I | re.S))
        record.update(state='completed', supported=supported, finish_reason='stop', checked_at=time.time())
        temporary = path.with_suffix(f'.{uuid.uuid4().hex}.tmp')
        temporary.write_text(json.dumps(record), encoding='utf-8')
        os.replace(temporary, path)
        return supported
