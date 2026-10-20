"""Frozen sidecar graphics for the existing device image journal. No remote I/O."""
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict
import hashlib
from io import BytesIO
import json
import os
import re
import uuid

from PIL import Image

from app.services import feishu_native_images as images, feishu_receipt_service as receipts
from app.services.feishu_service import FeishuError

PROTOCOL = 'feishu-graphic-delivery/1'
MAX_TOTAL_BYTES = 64 * 1024 * 1024


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _error(code='graphic_source_unverified'):
    return FeishuError('图形及正文尚未完整核验，原稿已保留；未准备完成前不会创建文档或通知',
                       409, code=code)


def _renderer():
    try:
        from app.services import summary_visual_png
        identity = summary_visual_png.renderer_identity()
        if (not isinstance(identity, dict) or identity.get('protocol') != 'summary-visual-png/1'
                or not re.fullmatch('[a-f0-9]{64}', identity.get('font_sha256', ''))
                or not identity.get('renderer_version') or not identity.get('fingerprint')):
            raise ValueError()
        return summary_visual_png, identity
    except (ImportError, OSError, ValueError, TypeError):
        raise _error('graphic_renderer_unavailable') from None


def verify_supported_presentation(artifacts, db, owner, task, metadata):
    """A display label cannot override an accepted generation's form."""
    from fastapi import HTTPException
    from sqlalchemy import select
    from app.db_models import SourceRequestDB
    from app.services.summary_visual_artifact import _folder, _authorization

    folder = artifacts.find_task_dir(task)
    if folder is None:
        raise ValueError('presentation source unavailable')
    # Ordinary intake also has accepted rows. Only explicit version bindings
    # identify a modern receipt; missing mutable files cannot erase that fact.
    with db.no_autoflush:
        saved_receipts = db.scalars(select(SourceRequestDB.receipt_json).where(
            SourceRequestDB.owner == owner, SourceRequestDB.task_id == task)).all()
    bound_version = False
    for raw in saved_receipts:
        saved = json.loads(raw or '{}')
        if not isinstance(saved, dict):
            raise ValueError('source receipt unavailable')
        bound_version |= (any(key in saved for key in
                              ('summary_snapshot_sha256', 'summary_visual_reference_sha256', 'meeting_version'))
                          or saved.get('contract') in ('meeting-summary-only-v1', 'meeting-fresh-asr-v1'))
    markers = ('new_generation.json', 'summary_generation_started', 'new_generation_started',
               'summary_visual.json')
    modern = (bound_version
              or any(key in metadata for key in ('operation_id', 'parent_task_id', 'source_version'))
              or any((folder / name).exists() or (folder / name).is_symlink() for name in markers))
    if not modern:
        return  # Original legacy supported forms have no accepted version contract.
    try:
        folder = _folder(artifacts, owner, task)
        _authorization(folder, owner, task, metadata['presentation'], lambda: nullcontext(db))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, HTTPException):
        raise ValueError('accepted presentation cannot be verified') from None


def _source(artifacts, owner, note_key, task, content, *, sessions):
    from app.services.summary_visual_artifact import read_summary_visual
    try:
        folder = artifacts.find_task_dir(task)
        if folder is None:
            raise ValueError()
        before = images._regular(folder / 'summary_visual.json', 128 * 1024 + 8192)
        wire = read_summary_visual(artifacts, owner, task, sessions=sessions)
        if (wire is None or wire['body_sha256'] != _hash(content.encode('utf-8'))
                or wire['presentation'] not in {'comic', 'infographic'}):
            raise ValueError()
        payload = json.loads(before.decode('utf-8'))
        assets, frames = [], {}
        for frame in wire['frames']:
            ref = f"/api/task/{task}/artifacts/screenshots/summary-source-{frame['screenshot_index']}.jpg"
            asset, data = images.read_asset(artifacts, owner, task, ref)
            if payload['screenshots'].get(asset['file_name']) != asset['sha256']:
                raise ValueError()
            assets.append(dict(frame_id=frame['id'], **asset))
            frames[frame['id']] = data
        if images._regular(folder / 'summary_visual.json', 128 * 1024 + 8192) != before:
            raise ValueError()
        source = dict(protocol=PROTOCOL, owner=owner, note_key=note_key, task_id=task,
                      body_sha256=_hash(content.encode('utf-8')), presentation=wire['presentation'],
                      sidecar_sha256=_hash(before), visual_sha256=receipts.fingerprint(wire),
                      frames=assets)
        return source, wire, frames
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise _error() from None


def capture(artifacts, db, owner, note, content, presentation):
    """Only NEW operations call this, under the final owner/note transaction."""
    try:
        source, wire, _ = _source(artifacts, owner, note.id, note.task_id, content,
                                  sessions=lambda: nullcontext(db))
    except FeishuError:
        # A valid presentation label alone cannot authorize graphical delivery.
        raise FeishuError('图形来源尚未准备好，纪要与原稿已保留；暂不支持漫画或信息图的飞书交付，'
                          '请使用桌面导出，尚未创建文档或通知', 422,
                          code='unsupported_graphic_delivery') from None
    if wire['presentation'] != presentation:
        raise _error()
    _, identity = _renderer()
    source['renderer'] = identity
    source['fingerprint'] = receipts.fingerprint(source)
    return source


def _validate_source(owner, job, source):
    if (not isinstance(source, dict) or source.get('protocol') != PROTOCOL
            or source.get('owner') != owner or source.get('note_key') != job.note_key
            or source.get('body_sha256') != _hash(job.content.encode('utf-8'))
            or source.get('fingerprint') != receipts.fingerprint({k: v for k, v in source.items()
                                                                  if k != 'fingerprint'})):
        raise _error('graphic_snapshot_changed')


def delivery_parts(artifacts, owner, job, snapshot):
    """Validate every frozen PNG before any write; never render during recovery."""
    source = snapshot.get('graphic_delivery')
    _validate_source(owner, job, source)
    manifest = snapshot.get('graphic_manifest')
    try:
        if (not isinstance(manifest, dict) or manifest.get('protocol') != PROTOCOL
                or manifest['source_fingerprint'] != source['fingerprint']
                or manifest['title_sha256'] != _hash(job.title.encode('utf-8'))
                or manifest['fingerprint'] != receipts.fingerprint({k: v for k, v in manifest.items()
                                                                   if k != 'fingerprint'})):
            raise ValueError()
        parts = manifest['parts']
        if (not isinstance(parts, list) or not 2 <= len(parts) <= images.MAX_IMAGES + 1
                or parts[-1] != dict(kind='text', content=job.content)
                or any(part.get('kind') != 'image' for part in parts[:-1])):
            raise ValueError()
        total = 0
        for part in parts[:-1]:
            asset, data = images.read_asset(artifacts, owner, source['task_id'], part['reference'])
            if asset != part['asset'] or asset['mime'] != 'image/png':
                raise ValueError()
            total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ValueError()
        return deepcopy(parts)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise _error('graphic_manifest_changed') from None


def _publish_png(artifacts, owner, task, data):
    """Publish content-addressed local derivatives; never replace originals."""
    folder = artifacts.find_task_dir(task)
    target = folder / 'screenshots'
    if (target.is_symlink() or getattr(target, 'is_junction', lambda: False)()
            or target.resolve().parent != folder.resolve()):
        raise _error()
    target.mkdir(exist_ok=True)
    name = 'feishu-graphic-' + _hash(data) + '.png'
    path = target / name
    if not path.exists():
        temporary = target / ('.feishu-graphic-' + str(uuid.uuid4()) + '.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # Hard-link installation is create-only. read_asset forbids links,
            # so unlink the temporary name before reading the published inode.
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
    reference = f'/api/task/{task}/artifacts/screenshots/{name}'
    asset, saved = images.read_asset(artifacts, owner, task, reference)
    if saved != data:
        raise _error('graphic_asset_changed')
    return dict(kind='image', caption='', reference=reference, asset=asset)


def prepare(artifacts, owner, job, snapshot, *, sessions):
    """Render ALL pages before Wiki/document allocation, then freeze one plan."""
    source = snapshot.get('graphic_delivery')
    _validate_source(owner, job, source)
    if 'graphic_manifest' in snapshot:
        delivery_parts(artifacts, owner, job, snapshot)
        return deepcopy(snapshot['graphic_manifest'])
    if job.document_id or int(job.written_blocks):
        raise _error('graphic_preflight_missing')
    fresh, wire, frames = _source(artifacts, owner, job.note_key, source['task_id'], job.content,
                                  sessions=sessions)
    renderer, identity = _renderer()
    fresh['renderer'] = identity
    fresh['fingerprint'] = receipts.fingerprint(fresh)
    if fresh != source:
        raise _error('graphic_source_changed')
    try:
        rendered = renderer.render_summary_visual_png(wire, frames, title=job.title)
        if rendered.renderer_identity != identity or not 1 <= len(rendered.pages) <= images.MAX_IMAGES:
            raise ValueError()
        total = 0
        # Fully decode/validate all pages before publishing any derivative.
        for page in rendered.pages:
            total += len(page.png_bytes)
            if (not 0 < len(page.png_bytes) <= images.MAX_BYTES or page.sha256 != _hash(page.png_bytes)
                    or type(page.width) is not int or type(page.height) is not int
                    or not 0 < page.width * page.height <= images.MAX_PIXELS):
                raise ValueError()
            with Image.open(BytesIO(page.png_bytes)) as picture:
                if picture.format != 'PNG' or picture.size != (page.width, page.height):
                    raise ValueError()
                picture.load()
        if total > MAX_TOTAL_BYTES:
            raise ValueError()
        parts = [_publish_png(artifacts, owner, source['task_id'], p.png_bytes) for p in rendered.pages]
        parts.append(dict(kind='text', content=job.content))
        manifest = dict(protocol=PROTOCOL, source_fingerprint=source['fingerprint'],
                        title_sha256=_hash(job.title.encode('utf-8')), renderer=identity,
                        render_fingerprint=rendered.fingerprint,
                        semantic_order=[asdict(item) for item in rendered.semantic_order],
                        page_semantic_refs=[list(p.semantic_refs) for p in rendered.pages], parts=parts)
        manifest['fingerprint'] = receipts.fingerprint(manifest)
        delivery_parts(artifacts, owner, job, {**snapshot, 'graphic_manifest': manifest})
        return manifest
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise _error('graphic_render_unavailable') from None
