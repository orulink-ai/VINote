"""VILab framed PCM transport. Session boundaries come from the service.

Packet size is a transport setting, never an ASR model's audio duration limit.
Only a final recognition is committed; partial text is not a saved transcript.
"""
import json
import logging
import math
import re
import ssl
import struct
import threading
import time
import wave
import httpx

from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed, ConnectionClosedError, ConnectionClosedOK
from websockets.exceptions import InvalidStatus
from fastapi import HTTPException

logger = logging.getLogger(__name__)
# Only service-declared failures with known transient semantics may replay.
_TRANSIENT_CODES = {"asr_timeout", "asr_stream_failed", "rate_limited",
                    "asr_rate_limited", "service_unavailable", "asr_unavailable"}
_KNOWN_CODES = _TRANSIENT_CODES | {"asr_failed", "asr_incomplete_result",
    "asr_protocol_error", "asr_provider_error", "auth_failed", "permission_denied",
    "quota_exceeded", "asr_provider_disabled", "asr_model_not_found",
    "asr_auth_failed", "asr_permission_denied", "asr_quota_exceeded",
    "asr_request_failed", "asr_connection_failed", "asr_provider_missing",
    "asr_deployment_unhealthy", "asr_model_load_failed",
    "audio_duration_exceeded", "empty_result_unverified", "asr_empty_result",
    "unknown_result", "unknown_error"}


def validated_empty_terminal_evidence(proof):
    """Validate/project typed facts; these alone never authorize a session/cache."""
    if (not isinstance(proof, dict) or type(proof.get('protocol')) is not int
            or proof.get('protocol') != 1 or proof.get('outcome') != 'provider_terminal_empty'
            or proof.get('terminalConfirmed') is not True or proof.get('inputComplete') is not True
            or proof.get('contentComplete') is not False or proof.get('silenceConfirmed') is not False
            or not isinstance(proof.get('provider'), str)
            or re.fullmatch(r'[a-z0-9_-]{1,64}', proof['provider']) is None):
        return None
    return {name: proof[name] for name in ('protocol', 'outcome', 'provider',
            'terminalConfirmed', 'inputComplete', 'contentComplete', 'silenceConfirmed')}


def confirmed_empty_terminal(event, session_id):
    """Require the typed terminal for this session and locally complete input."""
    if (event.get('code') != 'empty_result_unverified' or event.get('stage') != 'asr'
            or session_id is None or safe_session_id(event.get('sessionId')) != session_id):
        return None
    return validated_empty_terminal_evidence(event.get('terminalEvidence'))


def safe_session_id(value):
    # The service generates UUID session IDs. Reject arbitrary provider strings.
    if isinstance(value, str) and re.fullmatch(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        return value.lower()
    return None


_TRANSPORT_EVENTS = {"client_deadline", "audio_send_failed", "connection_closed",
                     "session_ended", "service_error"}
_TRANSPORT_EXCEPTION_TYPES = (
    (InvalidStatus, 'InvalidStatus'),
    (ConnectionClosedError, 'ConnectionClosedError'),
    (ConnectionClosedOK, 'ConnectionClosedOK'),
    (ConnectionClosed, 'ConnectionClosed'),
    (ssl.SSLCertVerificationError, 'SSLCertVerificationError'),
    (ssl.SSLEOFError, 'SSLEOFError'),
    (ssl.SSLError, 'SSLError'),
    (ConnectionResetError, 'ConnectionResetError'),
    (ConnectionAbortedError, 'ConnectionAbortedError'),
    (BrokenPipeError, 'BrokenPipeError'),
    (TimeoutError, 'TimeoutError'),
    (OSError, 'OSError'),
)
_TRANSPORT_EXCEPTION_CLASSES = {name for _, name in _TRANSPORT_EXCEPTION_TYPES} | {'OtherError'}
# Bounded local observations, not server/provider acknowledgements.
_TRANSPORT_NUMBER_LIMITS = {
    "local_send_bytes": 2 ** 40, "local_send_attempt_bytes": 2 ** 40,
    "local_send_packets": 2 ** 31 - 1, "local_send_attempt_packets": 2 ** 31 - 1,
    "elapsed_ms": 7 * 24 * 60 * 60 * 1000,
    "last_send_age_ms": 7 * 24 * 60 * 60 * 1000,
    "last_send_attempt_age_ms": 7 * 24 * 60 * 60 * 1000,
}


def safe_ws_close_code(value):
    # Received wire codes only: no synthesized 1005/1006 or reason text.
    if type(value) is int and (value in {1000, 1001, 1002, 1003, 1007, 1008,
            1009, 1010, 1011, 1012, 1013, 1014} or 3000 <= value <= 4999):
        return value
    return None


def safe_transport_diagnostic(raw):
    """Explicit allowlist shared by construction and persisted projections."""
    if not isinstance(raw, dict):
        return {}
    result = {}
    event = raw.get("transport_event")
    if isinstance(event, str) and event in _TRANSPORT_EVENTS:
        result["transport_event"] = event
    close_code = safe_ws_close_code(raw.get("ws_close_code"))
    if close_code is not None:
        result["ws_close_code"] = close_code
    exception_class = raw.get('transport_exception_class')
    if isinstance(exception_class, str) and exception_class in _TRANSPORT_EXCEPTION_CLASSES:
        result['transport_exception_class'] = exception_class
    if isinstance(raw.get('ws_proxy_mode'), str) and raw['ws_proxy_mode'] == 'disabled':
        result['ws_proxy_mode'] = 'disabled'
    for name, maximum in _TRANSPORT_NUMBER_LIMITS.items():
        value = raw.get(name)
        if type(value) is int and 0 <= value <= maximum:
            result[name] = value
    return result


def _transport_exception_diagnostic(error):
    # Connection policy only: this doesn't claim to bypass a system TUN/VPN.
    result = {'ws_proxy_mode': 'disabled'}
    if error is not None:
        result['transport_exception_class'] = next((name for kind, name in _TRANSPORT_EXCEPTION_TYPES
            if isinstance(error, kind)), 'OtherError')
        if isinstance(error, ConnectionClosed):
            code = safe_ws_close_code(getattr(getattr(error, 'rcvd', None), 'code', None))
            if code is not None:
                result['ws_close_code'] = code
    return result  # Never inspect exception messages, close reasons or URLs.


class _LocalTransportProgress:
    """Snapshot at failure; locks never span I/O, join or the audio claim lock."""
    def __init__(self):
        self.started_at = time.monotonic()
        self.last_attempt_at = self.last_send_at = None
        self.values = {name: 0 for name in (
            "local_send_bytes", "local_send_packets", "local_send_attempt_bytes",
            "local_send_attempt_packets")}
        self.lock = threading.Lock()

    def _add(self, bytes_name, packets_name, size):
        self.values[bytes_name] = min(_TRANSPORT_NUMBER_LIMITS[bytes_name],
                                      self.values[bytes_name] + size)
        self.values[packets_name] = min(_TRANSPORT_NUMBER_LIMITS[packets_name],
                                        self.values[packets_name] + 1)

    def attempt(self, size):
        with self.lock:
            self._add("local_send_attempt_bytes", "local_send_attempt_packets", size)
            self.last_attempt_at = time.monotonic()

    def sent(self, size):
        # ws.send returned locally. This is never a remote ACK or transcription.
        with self.lock:
            self._add("local_send_bytes", "local_send_packets", size)
            self.last_send_at = time.monotonic()

    def snapshot(self, event=None, close_code=None):
        with self.lock:
            now = time.monotonic()
            result = {**self.values, "transport_event": event, "ws_close_code": close_code}
            for name, previous in (("elapsed_ms", self.started_at),
                    ("last_send_age_ms", self.last_send_at),
                    ("last_send_attempt_age_ms", self.last_attempt_at)):
                if previous is not None and math.isfinite(now - previous):
                    result[name] = min(_TRANSPORT_NUMBER_LIMITS[name],
                                       max(0, int((now - previous) * 1000)))
            return safe_transport_diagnostic(result)


class ASRServiceError(RuntimeError):
    """Safe protocol classification; never retains upstream text or credentials."""
    def __init__(self, code, *, session_id=None, stage=None, sent_all=False, transport=None):
        self.code = code if isinstance(code, str) and code in _KNOWN_CODES else "unknown_error"
        self.session_id = safe_session_id(session_id)
        self.stage = stage if isinstance(stage, str) and stage in {"asr", "session", "audio"} else None
        self.sent_all = bool(sent_all)
        self._transport_diagnostic = safe_transport_diagnostic(transport)
        self.retry_reason = self.code if self.code in _TRANSIENT_CODES and not self.sent_all else None
        super().__init__("转写服务未能确认最终识别结果，请检查原任务后重试当前模型")

    @property
    def diagnostic(self):
        return {"code": self.code, "session_id": self.session_id,
                "stage": self.stage, "sent_all": self.sent_all, **self._transport_diagnostic}


def valid_duration_limit(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


class ASRSessionLimit(RuntimeError):
    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__("识别服务要求续接会话，已保留原录音")


def open_recognition(url, bearer):
    try:
        # The receive deadline below bounds a silent/stalled connection. Don't
        # let a shorter heartbeat timer cut off a provider finishing long audio.
        # websockets 15 otherwise reads environment AND Windows user proxies.
        # Direct target connection; retain the library's verified default TLS.
        return connect(url, proxy=None, additional_headers={"Authorization": "Bearer " + bearer}, open_timeout=15,
                       close_timeout=3, max_size=8 * 1024 * 1024, ping_timeout=None)
    except InvalidStatus as error:
        status = error.response.status_code
        if status in {401, 403}:
            failure = HTTPException(502, "云端服务未接受当前身份，请检查账号登录及服务端可信身份来源配置")
        else:
            failure = RuntimeError(f"VILab STT returned HTTP {status}")
        failure.asr_transport_diagnostic = _transport_exception_diagnostic(error)
        raise failure from None
    except (OSError, TimeoutError) as error:
        failure = httpx.ConnectError("转写连接暂时不可用")
        failure.asr_transport_diagnostic = _transport_exception_diagnostic(error)
        raise failure from error


def service_duration_limit(event):
    """Read a structured limit, or the deployed v1 service's explicit error.

    Never infer a limit from a provider/model name or a connection failure.
    """
    if event.get("code") != "audio_duration_exceeded":
        return None
    value = event.get("maxAudioDurationSeconds")
    if "maxAudioDurationSeconds" not in event:
        match = re.search(r"(?:the\s+)?(\d+(?:\.\d+)?)\s+(second|minute)\s+session limit",
                          str(event.get("message", "")), re.I)
        if match:
            value = float(match[1]) * (60 if match[2].lower() == "minute" else 1)
    return value if valid_duration_limit(value) else None


class _StreamDeadline:
    """One bounded upload window, then one confirmed-LAST finish window."""
    def __init__(self, duration):
        self.budget = duration * 1.5 + 90
        self.upload_deadline = time.monotonic() + self.budget
        self.completed_at = None
        self._expired = False
        self._lock = threading.Lock()

    def confirm_last(self):
        # The transition and timeout decision share a lock. A late sender cannot
        # revive an expired operation, and repeated observations cannot renew it.
        with self._lock:
            now = time.monotonic()
            if (not self._expired and self.completed_at is None
                    and now < self.upload_deadline):
                self.completed_at = now

    def remaining(self):
        with self._lock:
            deadline = (self.upload_deadline if self.completed_at is None
                        else self.completed_at + self.budget)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._expired = True
            return 0 if self._expired else remaining


def _validate_pcm_wav_data(wav_path):
    """Check chunk boundaries without loading PCM or trusting wave's frame rounding."""
    with open(wav_path, "rb") as source:
        size = source.seek(0, 2)
        source.seek(0)
        header = source.read(12)
        if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
            raise ValueError("转写音频必须是 RIFF WAV")
        position = 12
        data_bytes = None
        while position + 8 <= size:
            source.seek(position)
            chunk_id, length = struct.unpack("<4sI", source.read(8))
            if position + 8 + length > size:
                raise ValueError("WAV 音频块不完整")
            if chunk_id == b"data":
                if data_bytes is not None:
                    raise ValueError("WAV 必须且只能包含一个 data 音频块")
                if length % 2:
                    raise ValueError("WAV PCM16 音频块必须包含完整采样点")
                data_bytes = length
            position += 8 + length + length % 2
        if data_bytes is None:
            raise ValueError("WAV 缺少 data 音频块")
        return data_bytes


def recognize_pcm(origin, bearer, model, wav_path, *, start=0, end=None, progress=None):
    data_bytes = _validate_pcm_wav_data(wav_path)
    with wave.open(str(wav_path), "rb") as audio:
        if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (16000, 1, 2):
            raise ValueError("转写音频格式不匹配")
        if audio.getnframes() * 2 != data_bytes:
            raise ValueError("WAV 音频块与采样点数量不一致")
        rate = audio.getframerate()
        first = round(start * rate)
        last = min(audio.getnframes(), round(end * rate)) if end is not None else audio.getnframes()
        if last <= first:
            raise ValueError("转写音频区间为空")
    duration = (last - first) / rate
    url = origin.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/v1/asr/transcriptions"
    stop = threading.Event()
    sender_errors = []
    audio_attempted = threading.Event()
    audio_claim_lock = threading.Lock()
    sent_all = threading.Event()
    sending_last = threading.Event()
    deadline = _StreamDeadline(duration)
    local_transport = _LocalTransportProgress()
    session_id = None

    def stop_audio():
        # Linearize the failure decision with the sender claiming its first send.
        # Never hold this lock across socket I/O or join.
        with audio_claim_lock:
            stop.set()
            return audio_attempted.is_set()

    with open_recognition(url, bearer) as ws:
        ws.send(json.dumps({"type": "session.start", "model": model,
                            "audio": {"encoding": "pcm_s16le", "sampleRate": rate, "channels": 1}}))

        def send():
            sending_audio = False
            try:
                with wave.open(str(wav_path), "rb") as audio:
                    audio.setpos(first)
                    sent = 0
                    sequence = 0
                    # Small, paced packets keep buffers bounded for all runtimes.
                    packet_samples = rate // 5
                    while not stop.is_set() and audio.tell() < last:
                        samples = min(packet_samples, last - audio.tell())
                        pcm = audio.readframes(samples)
                        if len(pcm) != samples * 2:
                            raise ValueError("音频读取不完整，未发送截断数据")
                        flags = (1 if sequence == 0 else 0) | (2 if audio.tell() == last else 0)
                        if flags & 2:
                            sending_last.set()
                        with audio_claim_lock:
                            if stop.is_set():
                                return
                            audio_attempted.set()
                        sending_audio = True
                        local_transport.attempt(len(pcm))
                        ws.send(struct.pack("<4sBBBBQI", b"VLA2", 2, 1, flags, 0, sequence, len(pcm)) + pcm)
                        local_transport.sent(len(pcm))
                        sending_audio = False
                        if audio.tell() == last:
                            deadline.confirm_last()
                            sent_all.set()
                        sent += len(pcm) / (rate * 2)
                        sequence += 1
                        # A delayed packet must not trigger a catch-up burst.
                        # This is pacing, never a model/session duration cap.
                        if audio.tell() < last:
                            stop.wait(samples / rate)
            except Exception as error:
                sender_errors.append((error, "audio_send_failed" if sending_audio else None))
                stop.set()

        sender = None
        def failure(code, stage=None, transport_event=None, close_code=None, cause=None):
            attempted = stop_audio()
            error = ASRServiceError(code, session_id=session_id, stage=stage,
                                    sent_all=sent_all.is_set(),
                                    transport={**local_transport.snapshot(transport_event, close_code),
                                               **_transport_exception_diagnostic(cause)})
            if attempted:
                error.retry_reason = None
            logger.warning("ASR session failure diagnostic=%s", error.diagnostic)
            return error

        def transport_error(error, event, close_code=None, cause=None):
            # Preserve existing pre-audio exception/retry classification.
            error.asr_transport_diagnostic = {**local_transport.snapshot(event, close_code),
                                             **_transport_exception_diagnostic(cause)}
            return error

        try:
            while True:
                remaining = deadline.remaining()
                if remaining <= 0:
                    break
                if sender_errors:
                    if stop_audio():
                        raise failure("unknown_result", "asr", sender_errors[0][1], cause=sender_errors[0][0]) from None
                    raise transport_error(httpx.RemoteProtocolError(
                        "转写连接中断，已完成的识别结果保留"), sender_errors[0][1], cause=sender_errors[0][0]) from sender_errors[0][0]
                try:
                    event = json.loads(ws.recv(timeout=min(1, remaining)))
                except TimeoutError:
                    continue
                except (ConnectionClosed, OSError) as error:
                    close_code = safe_ws_close_code(getattr(getattr(error, "rcvd", None), "code", None))
                    if stop_audio():
                        raise failure("unknown_result", "asr", "connection_closed", close_code, cause=error) from None
                    raise transport_error(httpx.RemoteProtocolError(
                        "转写连接中断，未将临时文字当作完成结果"), "connection_closed", close_code, cause=error) from error
                if deadline.remaining() <= 0:
                    break
                kind = event.get("type")
                if session_id is None:
                    session_id = safe_session_id(event.get("sessionId"))
                if kind == "session.started" and sender is None:
                    sender = threading.Thread(target=send, daemon=True)
                    sender.start()
                elif kind == "asr.partial" and progress:
                    progress(min(duration, float(event.get("audioMs") or 0) / 1000), duration)
                elif kind == "asr.final":
                    if not sent_all.is_set() and not sending_last.is_set():
                        raise RuntimeError("识别服务提前结束，完整音频尚未提交")
                    if not sent_all.wait(timeout=3):
                        raise RuntimeError("识别服务提前结束，完整音频尚未提交")
                    if deadline.remaining() <= 0:
                        raise failure("unknown_result", "asr", "client_deadline") from None
                    text = event.get("text")
                    if not isinstance(text, str):
                        raise RuntimeError("转写结果格式异常，未保存此区间")
                    return {"text": text.strip(), "language": event.get("language"),
                            "segments": event.get("segments") or []}
                elif kind in {"error", "session.error"}:
                    proof = confirmed_empty_terminal(event, session_id)
                    if (proof is not None and (sent_all.is_set() or sending_last.is_set())
                            and sent_all.wait(timeout=3) and not sender_errors
                            and deadline.remaining() > 0):
                        return {"text": "", "segments": [],
                                "recognition_outcome": "provider_terminal_empty",
                                "terminal_evidence": proof}
                    limit = service_duration_limit(event)
                    if limit is not None:
                        raise ASRSessionLimit(limit)
                    # Do not expose upstream messages, secrets, or partial text.
                    raise failure(event.get("code"), event.get("stage"), "service_error") from None
                elif kind in {"session.cancelled", "session.completed"}:
                    raise failure("unknown_result", "asr", "session_ended") from None
            if stop_audio():
                raise failure("unknown_result", "asr", "client_deadline") from None
            raise transport_error(httpx.ReadTimeout("转写等待超时，未完成区间可以重试"), "client_deadline")
        finally:
            stop_audio()
            if sender:
                sender.join(timeout=3)
