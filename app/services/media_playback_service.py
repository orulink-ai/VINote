"""Seekable WebM playback derivatives; exports always retain the original bytes."""
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import threading
import uuid
from collections import OrderedDict
from fractions import Fraction
from pathlib import Path

from fastapi import HTTPException

_REMUX_LOCK = threading.Lock()
_VERIFIED = OrderedDict()
_TIMEOUT = 120
_LOCAL_WEBM_INPUT = ('-protocol_whitelist', 'file,pipe', '-f', 'matroska')


def _stamp(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino


def _unsafe(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def _preview_folder(source):
    return source.parent / '.playback-preview'


def _packet_manifest(path):
    """Hash every selected compressed packet with its DTS/PTS, without decoding.

    Remux may fill absent packet durations and change stream interleaving; those
    are not content changes. Per-track packet order, payload, DTS and PTS must
    remain identical. Tempfile stdout bounds memory for long recordings.
    """
    tracks = {}
    end = Fraction(0)
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        subprocess.run([
            'ffmpeg', '-nostdin', '-v', 'error', '-threads', '1',
            *_LOCAL_WEBM_INPUT, '-i', str(path),
            '-map', '0:v:0?', '-map', '0:a:0?', '-c', 'copy',
            '-f', 'framehash', '-hash', 'sha256', '-',
        ], check=True, stdout=output, stderr=errors, timeout=_TIMEOUT)
        if errors.tell() or output.tell() > 128 * 1024 * 1024:
            raise ValueError('Unverified media packets')
        output.seek(0)
        for raw in output:
            line = raw.decode('ascii').strip()
            if line.startswith(('#tb ', '#media_type ', '#codec_id ')):
                header = re.fullmatch(r'#(\w+) (\d+):\s*(.+)', line)
                if not header:
                    raise ValueError('Invalid packet header')
                name, index, value = header.groups()
                tracks.setdefault(int(index), {})[name] = value
            elif line and not line.startswith('#'):
                fields = [part.strip() for part in line.split(',')]
                index, dts, pts, duration, size, digest = fields[:6]
                index, dts, pts, duration, size = map(int, (index, dts, pts, duration, size))
                track = tracks[index]
                if size <= 0 or not re.fullmatch('[0-9a-f]{64}', digest):
                    raise ValueError('Invalid packet proof')
                side_data = ','.join(fields[6:])
                track.setdefault('hash', hashlib.sha256()).update(
                    f'{dts},{pts},{size},{digest},{side_data}\n'.encode('ascii'))
                track['count'] = track.get('count', 0) + 1
                track['end'] = max(track.get('end', Fraction(0)),
                                   (pts + max(duration, 0)) * Fraction(track['tb']))
                end = max(end, track['end'])
    if not tracks or any(not track.get('count') for track in tracks.values()) or end <= 0:
        raise ValueError('Empty media proof')
    signature = tuple((index, track['media_type'], track['codec_id'], track['tb'],
                       track['count'], track['hash'].hexdigest())
                      for index, track in sorted(tracks.items()))
    return {'streams': signature, 'end': float(end),
            'tails': {track['media_type']: float(track['end']) for track in tracks.values()},
            'video': any(track['media_type'] == 'video' for track in tracks.values())}


def _check_index(path, manifest):
    probe = subprocess.run([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json',
        *_LOCAL_WEBM_INPUT, str(path),
    ], check=True, capture_output=True, timeout=_TIMEOUT)
    duration = float(json.loads(probe.stdout)['format']['duration'])
    if probe.stderr or not math.isfinite(duration) or duration <= 0 or abs(duration - manifest['end']) > .25:
        raise ValueError('Unverified preview duration')
    # Tracks may end at different times. Exercise each one's actual tail, so
    # neither an audio-only tail nor a video-only tail is mistaken for truncation.
    for kind, end in manifest['tails'].items():
        tail = subprocess.run([
            'ffmpeg', '-nostdin', '-v', 'error', '-threads', '1',
            '-ss', str(max(0, end - 3)), *_LOCAL_WEBM_INPUT, '-i', str(path), '-t', '3',
            '-map', '0:v:0' if kind == 'video' else '0:a:0',
            '-progress', 'pipe:1', '-f', 'null', '-',
        ], check=True, capture_output=True, timeout=_TIMEOUT)
        progress = dict(line.split('=', 1) for line in tail.stdout.decode('ascii').splitlines() if '=' in line)
        if tail.stderr or progress.get('progress') != 'end':
            raise ValueError('Unverified preview seek')
        counter = 'frame' if kind == 'video' else 'out_time_us'
        valid = int(progress.get(counter, '0')) > 0
        if not valid:
            raise ValueError('Empty preview tail')


def _verify(path, source_manifest):
    preview = _packet_manifest(path)
    if preview['streams'] != source_manifest['streams']:
        raise ValueError('Incomplete preview packets')
    _check_index(path, source_manifest)


def playback_file(source: Path) -> Path:
    """Only call after the route has authorized and resolved the original.

    MediaRecorder WebM may omit duration/Cues. A disk-to-disk stream copy
    finalizes those indexes without decoding video or changing the original.
    """
    if _unsafe(source) or not source.is_file():
        raise HTTPException(404, '原文件不可用')
    if source.suffix.lower() != '.webm':
        return source
    source = source.resolve()
    stamp = _stamp(source)
    identity = f'{source}\0{stamp[0]}\0{stamp[1]}'
    key = hashlib.sha256(identity.encode()).hexdigest()
    folder = _preview_folder(source)
    if _unsafe(folder):
        raise HTTPException(409, '预览位置异常，原文件仍可导出')
    try:
        folder.mkdir(exist_ok=True)
    except OSError:
        raise HTTPException(409, '视频预览准备失败，可重新加载或导出原文件') from None
    target = folder / f'{key}.webm'
    if _unsafe(target):
        raise HTTPException(409, '预览位置异常，原文件仍可导出')
    if not _REMUX_LOCK.acquire(timeout=60):
        raise HTTPException(409, '视频预览正在准备，请稍后重新加载')
    temporary = folder / f'{uuid.uuid4().hex}.tmp.webm'
    try:
        if _unsafe(folder) or _unsafe(target):
            raise ValueError('Unsafe preview location')
        cache_key = (source, target)
        if target.is_file() and _VERIFIED.get(cache_key) == (stamp, _stamp(target)):
            if _stamp(source) != stamp:
                raise ValueError('Source changed')
            return target
        manifest = _packet_manifest(source)
        if target.is_file() and target.stat().st_size:
            try:
                _verify(target, manifest)
            except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, ArithmeticError):
                pass  # Invalid derived cache may be rebuilt; never serve it.
            else:
                if _stamp(source) != stamp:
                    raise ValueError('Source changed')
                _VERIFIED[cache_key] = (stamp, _stamp(target))
                if len(_VERIFIED) > 64:
                    _VERIFIED.popitem(last=False)
                return target
        subprocess.run([
            'ffmpeg', '-nostdin', '-y', '-v', 'error', '-threads', '1',
            *_LOCAL_WEBM_INPUT, '-i', str(source), '-map', '0:v:0?', '-map', '0:a:0?',
            '-c', 'copy', '-f', 'webm', str(temporary),
        ], check=True, capture_output=True, timeout=120)
        if not temporary.is_file() or not temporary.stat().st_size:
            raise ValueError('Empty preview')
        _verify(temporary, manifest)
        if _stamp(source) != stamp:
            raise ValueError('Source changed')
        with temporary.open('r+b') as complete:
            os.fsync(complete.fileno())
        os.replace(temporary, target)
        _VERIFIED[cache_key] = (stamp, _stamp(target))
        if len(_VERIFIED) > 64:
            _VERIFIED.popitem(last=False)
        return target
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, ArithmeticError):
        raise HTTPException(409, '视频预览准备失败，可重新加载或导出原文件') from None
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass  # An unpublished UUID temporary file is never a cache hit.
        finally:
            _REMUX_LOCK.release()
