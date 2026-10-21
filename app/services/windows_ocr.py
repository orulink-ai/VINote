"""Opt-in, offline Windows OCR. No cache writes or generation integration.

Each batch is atomic: any validation/transport/engine failure discards all OCR
text. Inputs must be absolute local regular JPEG/PNG files with caller-supplied
SHA256. One fixed PowerShell program receives data only on stdin; no user data
is executable code. Restricted/AllSigned policies fail closed (no policy override).
The host's existing Chinese/other language resources are used without downloads.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import ntpath
import os
import re
import stat
import subprocess
import threading
import time
import warnings
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Sequence

from PIL import Image, UnidentifiedImageError


class OCRFailure(str, Enum):
    UNSUPPORTED_OS = 'unsupported_os'
    BUSY = 'busy'
    INVALID_REQUEST = 'invalid_request'
    UNSAFE_PATH = 'unsafe_path'
    IMAGE_UNAVAILABLE = 'image_unavailable'
    IMAGE_CHANGED = 'image_changed'
    HASH_MISMATCH = 'hash_mismatch'
    IMAGE_LIMIT = 'image_limit'
    INVALID_IMAGE = 'invalid_image'
    POWERSHELL_UNAVAILABLE = 'powershell_unavailable'
    POLICY_BLOCKED = 'policy_blocked'
    ENGINE_UNAVAILABLE = 'engine_unavailable'
    LANGUAGE_UNAVAILABLE = 'language_unavailable'
    ENGINE_FAILED = 'engine_failed'
    BATCH_TIMEOUT = 'batch_timeout'
    IMAGE_TIMEOUT = 'image_timeout'
    OUTPUT_LIMIT = 'output_limit'
    TEXT_LIMIT = 'text_limit'
    INVALID_RESPONSE = 'invalid_response'


@dataclass(frozen=True)
class OCRInput:
    path: Path | str
    expected_sha256: str


@dataclass(frozen=True)
class OCRLimits:
    max_images: int = 64
    max_image_bytes: int = 2 * 1024 * 1024
    max_total_image_bytes: int = 16 * 1024 * 1024
    max_dimension: int = 4096
    max_pixels: int = 16_000_000
    max_output_bytes: int = 8 * 1024 * 1024
    max_text_chars: int = 16000
    max_lines: int = 2048
    max_words: int = 4096
    batch_timeout: float = 60
    image_timeout: float = 10


@dataclass(frozen=True)
class OCRCapability:
    status: str
    failure: OCRFailure | None = None
    engine: str = 'Windows.Media.Ocr.OcrEngine'
    languages: tuple[str, ...] = ()
    requested_language: str = 'zh-Hans-CN'
    actual_language: str | None = None
    os_version: str | None = None
    os_build: str | None = None
    engine_file_version: str | None = None
    powershell_version: str | None = None
    execution_policy: str | None = None
    max_image_dimension: int | None = None


@dataclass(frozen=True)
class OCRWord:
    text: str
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class OCRLine:
    text: str
    words: tuple[OCRWord, ...]


@dataclass(frozen=True)
class OCRItemResult:
    path: str
    expected_sha256: str
    status: str
    failure: OCRFailure | None = None
    text: str | None = None
    lines: tuple[OCRLine, ...] = ()
    width: int | None = None
    height: int | None = None
    text_angle: float | None = None
    elapsed_ms: float | None = None


@dataclass(frozen=True)
class OCRBatchResult:
    status: str
    capability: OCRCapability
    items: tuple[OCRItemResult, ...] = ()
    failure: OCRFailure | None = None
    inputs_verified_after: bool = False


class _Rejected(Exception):
    def __init__(self, code: OCRFailure):
        self.code = code


@dataclass(frozen=True)
class _Snapshot:
    path: str
    sha256: str
    size: int
    width: int
    height: int
    identity: tuple = field(repr=False)


_worker = threading.BoundedSemaphore(1)
_MAX_REQUEST_BYTES = 256 * 1024
_ENGINE = 'Windows.Media.Ocr.OcrEngine'


def _is_windows() -> bool:
    return os.name == 'nt'


def _local_drive(path: Path) -> bool:
    import ctypes
    return ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) in {3, 6}


def _powershell_executable() -> str:
    import ctypes
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise _Rejected(OCRFailure.POWERSHELL_UNAVAILABLE)
    path = Path(buffer.value) / 'WindowsPowerShell/v1.0/powershell.exe'
    if not path.is_file():
        raise _Rejected(OCRFailure.POWERSHELL_UNAVAILABLE)
    return str(path)


def _validate_options(language: str, limits: OCRLimits) -> None:
    if not isinstance(language, str) or not re.fullmatch(r'[A-Za-z0-9]{1,16}(?:-[A-Za-z0-9]{1,16}){0,5}', language):
        raise _Rejected(OCRFailure.INVALID_REQUEST)
    if not isinstance(limits, OCRLimits):
        raise _Rejected(OCRFailure.INVALID_REQUEST)
    caps = {'max_images': 64, 'max_image_bytes': 8*1024*1024,
            'max_total_image_bytes': 64*1024*1024, 'max_dimension': 10000,
            'max_pixels': 25_000_000, 'max_output_bytes': 16*1024*1024,
            'max_text_chars': 16000, 'max_lines': 2048, 'max_words': 4096}
    for key, cap in caps.items():
        value = getattr(limits, key)
        if type(value) is not int or not 1 <= value <= cap:
            raise _Rejected(OCRFailure.INVALID_REQUEST)
    for key, cap in [('batch_timeout', 600), ('image_timeout', 30)]:
        value = getattr(limits, key)
        if type(value) not in (float, int) or not math.isfinite(value) or not .05 <= value <= cap:
            raise _Rejected(OCRFailure.INVALID_REQUEST)
    if limits.image_timeout > limits.batch_timeout:
        raise _Rejected(OCRFailure.INVALID_REQUEST)


def _remaining(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise _Rejected(OCRFailure.BATCH_TIMEOUT)
    return left


def _stat_identity(value: os.stat_result) -> tuple:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _snapshot(item: OCRInput, limits: OCRLimits) -> _Snapshot:
    if not isinstance(item, OCRInput) or not isinstance(item.path, (str, Path)) or not isinstance(item.expected_sha256, str) or not re.fullmatch('[a-fA-F0-9]{64}', item.expected_sha256):
        raise _Rejected(OCRFailure.INVALID_REQUEST)
    raw = str(item.path)
    _, tail = ntpath.splitdrive(raw)
    if (not raw or len(raw) > 1024 or any(ord(c) < 32 for c in raw)
            or raw.startswith(('\\', '//')) or ':' in tail or '://' in raw):
        raise _Rejected(OCRFailure.UNSAFE_PATH)
    path = Path(raw)
    if not path.is_absolute() or '..' in path.parts or not _local_drive(path):
        raise _Rejected(OCRFailure.UNSAFE_PATH)
    try:
        for candidate in (path, *path.parents):
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise _Rejected(OCRFailure.UNSAFE_PATH)
        if os.path.normcase(str(path.resolve(strict=True))) != os.path.normcase(str(path)):
            raise _Rejected(OCRFailure.UNSAFE_PATH)
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise _Rejected(OCRFailure.UNSAFE_PATH)
        if not 0 < before.st_size <= limits.max_image_bytes:
            raise _Rejected(OCRFailure.IMAGE_LIMIT)
        with path.open('rb') as handle:
            data = handle.read(limits.max_image_bytes + 1)
        if len(data) != before.st_size or _stat_identity(before) != _stat_identity(path.stat()):
            raise _Rejected(OCRFailure.IMAGE_CHANGED)
        digest = hashlib.sha256(data).hexdigest()
        if digest != item.expected_sha256.lower():
            raise _Rejected(OCRFailure.HASH_MISMATCH)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                if not 0 < width <= limits.max_dimension or not 0 < height <= limits.max_dimension or width*height > limits.max_pixels:
                    raise _Rejected(OCRFailure.IMAGE_LIMIT)
                if image.format not in {'JPEG', 'PNG'} or getattr(image, 'n_frames', 1) != 1:
                    raise _Rejected(OCRFailure.INVALID_IMAGE)
                image.verify()
        return _Snapshot(str(path), digest, len(data), width, height, _stat_identity(before))
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, SyntaxError, ValueError) as exc:
        raise _Rejected(OCRFailure.INVALID_IMAGE) from exc
    except OSError as exc:
        raise _Rejected(OCRFailure.IMAGE_UNAVAILABLE) from exc


def _invoke(payload: dict, deadline: float, output_limit: int) -> dict:
    encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode('ascii')
    if len(encoded) > _MAX_REQUEST_BYTES:
        raise _Rejected(OCRFailure.INVALID_REQUEST)
    command = [_powershell_executable(), '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', _POWERSHELL_SCRIPT]
    # Credentials, Python paths and arbitrary PowerShell module paths are not inherited.
    environment = {k: v for k, v in os.environ.items() if k.upper() in {
        'SYSTEMROOT', 'WINDIR', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP',
    }}
    buffers = [bytearray(), bytearray()]
    exceeded = threading.Event()
    io_failed = threading.Event()
    lock = threading.Lock()
    count = 0
    process = None
    threads = []

    def read_pipe(stream, index):
        nonlocal count
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                with lock:
                    count += len(chunk)
                    if count > output_limit:
                        exceeded.set()
                        return
                    buffers[index].extend(chunk)
        except (OSError, ValueError):
            io_failed.set()
        finally:
            stream.close()

    def write_pipe():
        try:
            process.stdin.write(encoded)
            process.stdin.flush()
        except (OSError, ValueError):
            io_failed.set()
        finally:
            process.stdin.close()

    try:
        _remaining(deadline)
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, shell=False, close_fds=True, env=environment,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000))
        for target, args in [(read_pipe, (process.stdout, 0)), (read_pipe, (process.stderr, 1)), (write_pipe, ())]:
            thread = threading.Thread(target=target, args=args, daemon=True)
            threads.append(thread)
            thread.start()
        while process.poll() is None:
            if exceeded.is_set():
                raise _Rejected(OCRFailure.OUTPUT_LIMIT)
            try:
                process.wait(timeout=min(.025, _remaining(deadline)))
            except subprocess.TimeoutExpired:
                pass
        for thread in threads:
            thread.join(timeout=_remaining(deadline))
        if exceeded.is_set():
            raise _Rejected(OCRFailure.OUTPUT_LIMIT)
        if any(t.is_alive() for t in threads):
            raise _Rejected(OCRFailure.BATCH_TIMEOUT)
        if io_failed.is_set() or process.returncode != 0 or buffers[1]:
            raise _Rejected(OCRFailure.ENGINE_FAILED)
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate key')
                result[key] = value
            return result
        result = json.loads(bytes(buffers[0]).decode('utf-8-sig'), object_pairs_hook=unique_pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        if not isinstance(result, dict):
            raise ValueError('object required')
        return result
    except (OSError, subprocess.SubprocessError) as exc:
        raise _Rejected(OCRFailure.ENGINE_FAILED) from exc
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise _Rejected(OCRFailure.INVALID_RESPONSE) from exc
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass  # The process may have exited between poll and kill.
            try:
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
            for thread in threads:
                thread.join(timeout=.1)


def _keys(value: object, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise _Rejected(OCRFailure.INVALID_RESPONSE)
    return value


def _number(value: object, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise _Rejected(OCRFailure.INVALID_RESPONSE)
    return value


def _capability(raw: object, language: str) -> OCRCapability:
    row = _keys(raw, {'status', 'failure', 'engine', 'languages', 'requested_language', 'actual_language',
                     'os_version', 'os_build', 'engine_file_version', 'powershell_version', 'execution_policy', 'max_image_dimension'})
    if row['engine'] != _ENGINE or row['requested_language'] != language or not isinstance(row['status'], str) or row['status'] not in {'available', 'unavailable', 'failed'}:
        raise _Rejected(OCRFailure.INVALID_RESPONSE)
    for key in ['os_version', 'os_build', 'engine_file_version', 'powershell_version', 'execution_policy', 'actual_language']:
        if row[key] is not None and (not isinstance(row[key], str) or not 0 < len(row[key]) <= 128):
            raise _Rejected(OCRFailure.INVALID_RESPONSE)
    languages = row['languages']
    if not isinstance(languages, list) or len(languages) > 128 or any(not isinstance(x, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,96}', x) for x in languages) or len(set(languages)) != len(languages):
        raise _Rejected(OCRFailure.INVALID_RESPONSE)
    try:
        failure = OCRFailure(row['failure']) if row['failure'] is not None else None
    except (ValueError, TypeError) as exc:
        raise _Rejected(OCRFailure.INVALID_RESPONSE) from exc
    maximum = row['max_image_dimension']
    if maximum is not None and (type(maximum) is not int or not 1 <= maximum <= 100000):
        raise _Rejected(OCRFailure.INVALID_RESPONSE)
    if row['status'] == 'available':
        if failure is not None or row['actual_language'] != language or language not in languages or maximum is None:
            raise _Rejected(OCRFailure.INVALID_RESPONSE)
    elif failure is None or row['actual_language'] is not None:
        raise _Rejected(OCRFailure.INVALID_RESPONSE)
    return OCRCapability(**{**row, 'languages':tuple(languages), 'failure':failure})


def _parse(raw: dict, snapshots: list[_Snapshot], language: str, limits: OCRLimits) -> OCRBatchResult:
    _keys(raw, {'protocol', 'status', 'failure', 'capability', 'items'})
    if type(raw['protocol']) is not int or raw['protocol'] != 1 or not isinstance(raw['status'], str) or raw['status'] not in {'completed', 'failed'}:
        raise _Rejected(OCRFailure.INVALID_RESPONSE)
    capability = _capability(raw['capability'], language)
    if raw['status'] == 'failed':
        try:
            failure = OCRFailure(raw['failure'])
        except (ValueError, TypeError) as exc:
            raise _Rejected(OCRFailure.INVALID_RESPONSE) from exc
        if raw['items'] != []:
            raise _Rejected(OCRFailure.INVALID_RESPONSE)
        return _failure(failure, language, snapshots, capability)
    if raw['failure'] is not None or capability.status != 'available' or not isinstance(raw['items'], list) or len(raw['items']) != len(snapshots):
        raise _Rejected(OCRFailure.INVALID_RESPONSE)
    results = []
    for index, (row, expected) in enumerate(zip(raw['items'], snapshots)):
        _keys(row, {'index', 'status', 'sha256', 'size', 'width', 'height', 'text', 'lines', 'text_angle', 'elapsed_ms'})
        if (type(row['index']) is not int or row['index'] != index or row['sha256'] != expected.sha256
                or any(type(row[k]) is not int or row[k] != getattr(expected, k) for k in ('size','width','height'))
                or not isinstance(row['status'], str) or row['status'] not in {'recognized', 'no_text_detected'}):
            raise _Rejected(OCRFailure.INVALID_RESPONSE)
        text = row['text']
        if not isinstance(text, str) or len(text) > limits.max_text_chars:
            raise _Rejected(OCRFailure.TEXT_LIMIT if isinstance(text, str) else OCRFailure.INVALID_RESPONSE)
        if (row['status'] == 'recognized') != bool(text.strip()):
            raise _Rejected(OCRFailure.INVALID_RESPONSE)
        if not isinstance(row['lines'], list) or len(row['lines']) > limits.max_lines:
            raise _Rejected(OCRFailure.OUTPUT_LIMIT)
        lines, words_total, line_chars, word_chars = [], 0, 0, 0
        for line in row['lines']:
            _keys(line, {'text', 'words'})
            if not isinstance(line['text'], str) or not isinstance(line['words'], list):
                raise _Rejected(OCRFailure.INVALID_RESPONSE)
            line_chars += len(line['text'])
            words_total += len(line['words'])
            if words_total > limits.max_words:
                raise _Rejected(OCRFailure.OUTPUT_LIMIT)
            words = []
            for word in line['words']:
                _keys(word, {'text', 'x', 'y', 'width', 'height'})
                if not isinstance(word['text'], str):
                    raise _Rejected(OCRFailure.INVALID_RESPONSE)
                word_chars += len(word['text'])
                if word_chars > limits.max_text_chars:
                    raise _Rejected(OCRFailure.TEXT_LIMIT)
                coords = {k:_number(word[k], 0, expected.width if k in {'x','width'} else expected.height) for k in ('x','y','width','height')}
                if coords['x']+coords['width'] > expected.width+.01 or coords['y']+coords['height'] > expected.height+.01:
                    raise _Rejected(OCRFailure.INVALID_RESPONSE)
                words.append(OCRWord(word['text'], **coords))
            if line_chars > limits.max_text_chars:
                raise _Rejected(OCRFailure.TEXT_LIMIT)
            lines.append(OCRLine(line['text'], tuple(words)))
        angle = row['text_angle']
        if (text.strip() and not any(w.text.strip() for line in lines for w in line.words)
                or not text.strip() and any(line.text.strip() or any(w.text.strip() for w in line.words) for line in lines)):
            raise _Rejected(OCRFailure.INVALID_RESPONSE)
        if angle is not None:
            _number(angle, -360, 360)
        elapsed = _number(row['elapsed_ms'], 0, limits.image_timeout*1000+1)
        results.append(OCRItemResult(expected.path, expected.sha256, row['status'], text=text,
            lines=tuple(lines), width=expected.width, height=expected.height, text_angle=angle, elapsed_ms=elapsed))
    return OCRBatchResult('completed', capability, tuple(results))


def _failure(code: OCRFailure, language: str, snapshots: list[_Snapshot] = (), capability: OCRCapability | None = None) -> OCRBatchResult:
    return OCRBatchResult('failed', capability or OCRCapability('unavailable', failure=code, requested_language=language),
        tuple(OCRItemResult(s.path, s.sha256, 'failed', failure=code) for s in snapshots), code)


def _run(inputs: Sequence[OCRInput], language: str, limits: OCRLimits, describe: bool) -> OCRBatchResult:
    snapshots = []
    capability = None
    if not _worker.acquire(blocking=False):
        return _failure(OCRFailure.BUSY, language)
    try:
        _validate_options(language, limits)
        deadline = time.monotonic()+limits.batch_timeout
        if not _is_windows():
            raise _Rejected(OCRFailure.UNSUPPORTED_OS)
        if not isinstance(inputs, (list, tuple)) or (not describe and not 1 <= len(inputs) <= limits.max_images):
            raise _Rejected(OCRFailure.INVALID_REQUEST)
        for item in inputs:
            _remaining(deadline)
            snapshots.append(_snapshot(item, limits))
        if len({s.path.casefold() for s in snapshots}) != len(snapshots):
            raise _Rejected(OCRFailure.INVALID_REQUEST)
        if sum(s.size for s in snapshots) > limits.max_total_image_bytes:
            raise _Rejected(OCRFailure.IMAGE_LIMIT)
        payload = {'protocol':1, 'mode':'describe' if describe else 'recognize', 'language':language,
            'batch_ms':max(1, int(_remaining(deadline)*1000)), 'image_ms':int(limits.image_timeout*1000),
            'max_text_chars':limits.max_text_chars, 'max_output_bytes':limits.max_output_bytes,
            'max_lines':limits.max_lines, 'max_words':limits.max_words,
            'items':[{'path':s.path, 'sha256':s.sha256, 'size':s.size, 'width':s.width, 'height':s.height} for s in snapshots]}
        result = _parse(_invoke(payload, deadline, limits.max_output_bytes), snapshots, language, limits)
        capability = result.capability
        # Independently re-read path, identity, bytes and dimensions, including failed
        # child replies; no returned text survives an input mutation.
        for snapshot in snapshots:
            _remaining(deadline)
            try:
                after = _snapshot(OCRInput(snapshot.path, snapshot.sha256), limits)
            except _Rejected as exc:
                raise _Rejected(OCRFailure.IMAGE_CHANGED) from exc
            if after != snapshot:
                raise _Rejected(OCRFailure.IMAGE_CHANGED)
        _remaining(deadline)
        return replace(result, inputs_verified_after=bool(snapshots))
    except _Rejected as exc:
        return _failure(exc.code, language, snapshots, capability)
    finally:
        _worker.release()


def describe_capability(*, language: str = 'zh-Hans-CN', limits: OCRLimits = OCRLimits()) -> OCRCapability:
    """Probe actual installed OS OCR resources; never recognize, install or download."""
    result = _run([], language, limits, True)
    if result.status == 'failed' and result.capability.status == 'available':
        return replace(result.capability, status='failed', failure=result.failure)
    return result.capability


def recognize_batch(inputs: Sequence[OCRInput], *, language: str = 'zh-Hans-CN', limits: OCRLimits = OCRLimits()) -> OCRBatchResult:
    """One hidden process per admitted batch. No fallback, retries, writes or truncation.

    Total deadline includes pre/post validation and child startup. Native async
    operations also share a per-image deadline. Killing/reaping may take up to
    ~1.3 seconds beyond the deadline. The parent bounds combined stdout/stderr.
    A completed batch can contain recognized or no_text_detected items; failed
    batches contain no OCR text. inputs_verified_after reports whether postchecks
    ran; a timed-out/invalid response never implies inputs were unchanged. Deadlines
    are checked between bounded local validation reads (OS I/O is not preemptible).
    No confidence/model-version claims are invented.
    """
    return _run(inputs, language, limits, False)


_POWERSHELL_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$request = $null
$cap = [ordered]@{status='unavailable';failure='engine_unavailable';engine='Windows.Media.Ocr.OcrEngine';languages=@();requested_language='zh-Hans-CN';actual_language=$null;os_version=$null;os_build=$null;engine_file_version=$null;powershell_version=$PSVersionTable.PSVersion.ToString();execution_policy=$null;max_image_dimension=$null}
$clock = [Diagnostics.Stopwatch]::StartNew()
function Fail([string]$code) { throw [InvalidOperationException]::new('OCR:'+$code) }
function Budget {
    if ($clock.ElapsedMilliseconds -ge $request.batch_ms) { Fail 'batch_timeout' }
    if ($null -ne $script:imageClock -and $script:imageClock.ElapsedMilliseconds -ge $request.image_ms) { Fail 'image_timeout' }
}
function Await($operation, [Type]$type) {
    Budget
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
    $remaining = [Math]::Min($request.batch_ms-$clock.ElapsedMilliseconds, $request.image_ms-$script:imageClock.ElapsedMilliseconds)
    if ($remaining -le 0 -or -not $task.Wait([int][Math]::Max(1,$remaining))) {
        try { $operation.Cancel() } catch {}
        Budget
        Fail 'image_timeout'
    }
    Budget
    return $task.Result
}
function CheckPath([string]$path) {
    if ($path.StartsWith('\') -or $path.StartsWith('//') -or $path.Substring(2).Contains(':') -or [IO.Path]::GetFullPath($path) -ne $path) { Fail 'unsafe_path' }
    $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($path))
    if ($drive.DriveType -notin @([IO.DriveType]::Fixed,[IO.DriveType]::Ram)) { Fail 'unsafe_path' }
    $current = Get-Item -LiteralPath $path -Force
    while ($null -ne $current) {
        if (($current.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { Fail 'unsafe_path' }
        if ($current -is [IO.FileInfo]) { $current=$current.Directory } else { $current=$current.Parent }
    }
}
function HashStream($stream) {
    $stream.Position=0
    $sha=[Security.Cryptography.SHA256]::Create()
    try { $digest=([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
    $stream.Position=0
    Budget
    return $digest
}
function Emit($value) {
    $json = ConvertTo-Json -InputObject $value -Depth 12 -Compress
    if ([Text.Encoding]::UTF8.GetByteCount($json) -gt $request.max_output_bytes) {
        $json = ConvertTo-Json -InputObject @{protocol=1;status='failed';failure='output_limit';capability=$cap;items=@()} -Depth 8 -Compress
    }
    [Console]::Out.Write($json)
}
try {
    $raw=[Console]::In.ReadToEnd()
    if ($raw.Length -gt 262144) { Fail 'invalid_request' }
    $request=ConvertFrom-Json -InputObject $raw
    $cap.requested_language=$request.language
    if ($request.protocol -ne 1 -or $request.mode -notin @('describe','recognize') -or @($request.items).Count -gt 64) { Fail 'invalid_request' }
    $cap.execution_policy=(Get-ExecutionPolicy).ToString()
    if ($cap.execution_policy -in @('Restricted','AllSigned')) { $cap.failure='policy_blocked'; Fail 'policy_blocked' }
    $cap.os_version=[Environment]::OSVersion.Version.ToString()
    try {
        $build=Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -Name CurrentBuildNumber,UBR
        $cap.os_build=[string]$build.CurrentBuildNumber+'.'+[string]$build.UBR
    } catch {}
    try {
        $dll=Join-Path ([Environment]::SystemDirectory) 'Windows.Media.Ocr.dll'
        $cap.engine_file_version=[Diagnostics.FileVersionInfo]::GetVersionInfo($dll).FileVersion
    } catch {}
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
    [Windows.Globalization.Language, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
    $asTask=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
    $cap.languages=@([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })
    $cap.max_image_dimension=[Windows.Media.Ocr.OcrEngine]::MaxImageDimension
    $language=[Windows.Globalization.Language]::new($request.language)
    if (-not [Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($language)) { $cap.failure='language_unavailable'; Fail 'language_unavailable' }
    $engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
    if ($null -eq $engine) { Fail 'engine_unavailable' }
    $cap.actual_language=$engine.RecognizerLanguage.LanguageTag
    if ($cap.actual_language -ne $request.language) { $cap.actual_language=$null; $cap.failure='language_unavailable'; Fail 'language_unavailable' }
    $cap.status='available'; $cap.failure=$null
    Budget
    $items=[Collections.Generic.List[object]]::new()
    $index=0
    foreach ($item in $request.items) {
        $script:imageClock=[Diagnostics.Stopwatch]::StartNew()
        $file=$null; $stream=$null; $bitmap=$null
        try {
            CheckPath $item.path
            # FileShare.Read denies concurrent write/delete while this image is used.
            $file=[IO.FileStream]::new($item.path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
            if ($file.Length -ne $item.size) { Fail 'image_changed' }
            if ((HashStream $file) -ne $item.sha256) { Fail 'hash_mismatch' }
            $stream=[System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($file)
            $decoder=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
            if ($decoder.PixelWidth -ne $item.width -or $decoder.PixelHeight -ne $item.height) { Fail 'image_changed' }
            if ($item.width -gt $cap.max_image_dimension -or $item.height -gt $cap.max_image_dimension) { Fail 'image_limit' }
            $bitmap=Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
            if ($bitmap.PixelWidth -ne $item.width -or $bitmap.PixelHeight -ne $item.height) { Fail 'image_changed' }
            $ocr=Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
            $text=$ocr.Text
            if ($text.Length -gt $request.max_text_chars) { Fail 'text_limit' }
            if ($ocr.Lines.Count -gt $request.max_lines) { Fail 'output_limit' }
            $lines=[Collections.Generic.List[object]]::new(); $wordsTotal=0; $lineChars=0; $wordChars=0
            foreach ($line in $ocr.Lines) {
                $lineChars += $line.Text.Length
                if ($lineChars -gt $request.max_text_chars) { Fail 'text_limit' }
                $words=[Collections.Generic.List[object]]::new()
                foreach ($word in $line.Words) {
                    $wordsTotal++; $wordChars += $word.Text.Length
                    if ($wordsTotal -gt $request.max_words) { Fail 'output_limit' }
                    if ($wordChars -gt $request.max_text_chars) { Fail 'text_limit' }
                    $rect=$word.BoundingRect
                    $words.Add(@{text=$word.Text;x=$rect.X;y=$rect.Y;width=$rect.Width;height=$rect.Height})
                }
                $lines.Add(@{text=$line.Text;words=@($words.ToArray())})
            }
            $stream.Seek(0)
            if ((HashStream $file) -ne $item.sha256 -or $file.Length -ne $item.size) { Fail 'image_changed' }
            CheckPath $item.path
            Budget
            $status='recognized'; if ([string]::IsNullOrWhiteSpace($text)) { $status='no_text_detected' }
            $items.Add(@{index=$index;status=$status;sha256=$item.sha256;size=$item.size;width=$bitmap.PixelWidth;height=$bitmap.PixelHeight;text=$text;lines=@($lines.ToArray());text_angle=$ocr.TextAngle;elapsed_ms=$script:imageClock.Elapsed.TotalMilliseconds})
        } finally {
            if ($null -ne $bitmap) { $bitmap.Dispose() }
            if ($null -ne $stream) { $stream.Dispose() }
            if ($null -ne $file) { $file.Dispose() }
        }
        $script:imageClock=$null
        $index++
    }
    Budget
    Emit @{protocol=1;status='completed';failure=$null;capability=$cap;items=@($items.ToArray())}
} catch {
    $code='engine_failed'
    if ($_.Exception.Message -match '^OCR:([a-z_]+)$') { $code=$Matches[1] }
    if ($null -eq $request) { $request=@{max_output_bytes=8388608} }
    Emit @{protocol=1;status='failed';failure=$code;capability=$cap;items=@()}
}
'''
