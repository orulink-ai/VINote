"""VILab framed PCM recognition with service-declared session continuation."""
import subprocess
import logging
import math
import hashlib
import json
import os
import tempfile
import time
import uuid
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path

import httpx
from fastapi import HTTPException

from app.models.transcript import NoSpeechDetectedError, TranscriptResult, TranscriptSegment
from app.transcribers.base import Transcriber

logger = logging.getLogger(__name__)


class _CheckpointEvidenceUnavailable(ValueError):
    def __init__(self):
        super().__init__('原转写记录尚不能安全核验，原文件与记录已保留，未提交音频。')


def _save_checkpoint(path, checkpoint):
    """Publish one durable record before a plan or an audio dispatch is allowed."""
    temporary = path.with_suffix('.tmp')
    if path.is_symlink() or temporary.is_symlink():
        raise ValueError('转写记录位置无效，未提交音频')
    with temporary.open('w', encoding='utf-8') as target:
        json.dump(checkpoint, target, ensure_ascii=False, allow_nan=False)
        target.flush()
        os.fsync(target.fileno())
    temporary.replace(path)
    if os.name != 'nt':
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _empty_terminal_fields(part):
    """Preserve only revalidated typed facts, never trust arbitrary cache labels."""
    from app.services.asr_stream_service import validated_empty_terminal_evidence
    if 'recognition_outcome' not in part and 'terminal_evidence' not in part:
        return {}  # Historical finals remain historical, without invented proof.
    proof = validated_empty_terminal_evidence(part.get('terminal_evidence'))
    if (part.get('recognition_outcome') != 'provider_terminal_empty' or proof is None
            or part.get('text') != '' or part.get('segments', []) != []):
        raise ValueError('已保存的空终态证据无法核验，未提交音频')
    return {'recognition_outcome': 'provider_terminal_empty', 'terminal_evidence': proof}


def _confirmed_prefix(donor, total_frames):
    """Strict, bounded donor projection; never copy request/plan/unknown state."""
    if not isinstance(donor, dict) or not isinstance(donor.get('completed'), list):
        raise ValueError('Invalid donor')
    if len(donor['completed']) > 65536:
        raise ValueError('Oversized donor')

    def frame(value):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Non-sample boundary')
        result = round(value * 16000)
        if not 0 <= result <= total_frames or abs(value * 16000 - result) > 1e-7:
            raise ValueError('Non-sample boundary')
        return result

    parts, cursor = [], 0
    for part in donor['completed']:
        if not isinstance(part, dict):
            raise ValueError('Invalid confirmed interval')
        first, end = frame(part.get('start')), frame(part.get('end'))
        if first != cursor or end <= first or not isinstance(part.get('text'), str):
            raise ValueError('Non-contiguous confirmed prefix')
        language = part.get('language')
        if language is not None and not isinstance(language, str):
            raise ValueError('Invalid language')
        segments = []
        for segment in part.get('segments') or []:
            if (not isinstance(segment, dict) or type(segment.get('start')) not in (int, float)
                    or type(segment.get('end')) not in (int, float)
                    or not first / 16000 <= segment['start'] < segment['end'] <= end / 16000
                    or not isinstance(segment.get('text'), str)):
                segments = []
                break
            segments.append({key: segment[key] for key in ('start', 'end', 'text')})
        if ''.join(''.join(s['text'].split()) for s in segments) != ''.join(part['text'].split()):
            segments = []
        parts.append({'start': first / 16000, 'end': end / 16000, 'text': part['text'],
                      'language': language, 'segments': segments, **_empty_terminal_fields(part)})
        cursor = end
    inflight = donor.get('inflight')
    if inflight is not None:
        if (not isinstance(inflight, dict) or type(inflight.get('start_frame')) is not int
                or type(inflight.get('end_frame')) is not int
                or not cursor <= inflight['start_frame'] < inflight['end_frame'] <= total_frames):
            raise ValueError('Unknown overlaps confirmed evidence')
    return parts


def _read_donor(folder, total_frames):
    """Caller holds the donor OS lock until its entire execution completes."""
    sentinel = folder / 'recognition.lock'
    try:
        if folder.is_symlink() or sentinel.exists() or sentinel.is_symlink():
            raise ValueError('Legacy donor sentinel')
        path = folder / 'recognition.json'
        if (folder / 'recognition.tmp').exists() or (folder / 'recognition.tmp').is_symlink():
            raise ValueError('Uncommitted donor record')
        if path.is_symlink():
            raise ValueError('Invalid donor path')
        if not path.exists():
            return [], None
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('Oversized donor')
        with path.open('rb') as source:
            raw = source.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError('Oversized donor')
        parts = _confirmed_prefix(json.loads(raw), total_frames)
        return parts, hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, TypeError, OverflowError):
        raise _CheckpointEvidenceUnavailable() from None


class VILabTranscriber(Transcriber):
    provider = "vilab-server"
    # A model name is not a transport capability or a duration limit.
    max_request_duration_seconds = None
    def __init__(self, base_url: str, api_key: str, model: str | None = None, language: str | None = None, cloud_user_id: str | None = None, cloud_connection_id: str | None = None, cloud_connection_auth_mode: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.language = language
        self.cloud_user_id = cloud_user_id
        self.cloud_connection_id = cloud_connection_id
        self.cloud_connection_auth_mode = cloud_connection_auth_mode
        self.progress_callback = None
        self._policy_cache = None

    @staticmethod
    def _retry_reason(exc):
        from app.services.asr_stream_service import ASRServiceError
        # A meeting recording is submitted exactly once. The checkpoint marker,
        # not the exception class, decides whether a replay is ever authorized.
        if getattr(exc, "asr_single_attempt", False):
            return None
        if isinstance(exc, ASRServiceError):
            return exc.retry_reason
        # The shared service wraps upstream status codes in a safe, exact
        # message. Its outer HTTP 502 also covers identity failures: never use
        # that outer status, or substring matches, to decide a retry.
        network_errors = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
        if isinstance(exc, HTTPException) and exc.status_code in {401, 403}:
            return None
        if isinstance(exc, network_errors):
            return "network"
        detail = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
        if detail in {"无法连接云端模型服务，请稍后重试", "VILab STT connection failed or timed out"}:
            # The shared wrapper also catches non-network RequestErrors such
            # as UnsupportedProtocol. Their original context remains present
            # even when the safe public exception uses `from None`.
            context = exc.__context__
            if isinstance(context, httpx.RequestError) and not isinstance(context, network_errors):
                return None
            return "network"
        for code in (429, 502, 503, 504):
            if detail in {f"云端模型请求失败（HTTP {code}）", f"VILab STT returned HTTP {code}"}:
                return f"http_{code}"
        return None

    def transcribe(self, file_path: str) -> TranscriptResult:
        # Native streaming providers accept 16 kHz mono PCM WAV, including HTTP uploads.
        with tempfile.TemporaryDirectory(prefix="vinote-stt-") as folder:
            normalized = str(Path(folder) / "audio.wav")
            try:
                subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", file_path,
                                "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", normalized],
                               check=True, capture_output=True, timeout=600)
            except (subprocess.SubprocessError, OSError):
                raise RuntimeError("无法转换音频，请检查 ffmpeg 和输入文件") from None
            attempts = []
            from app.services.tracing_service import observation, update_current
            for attempt in range(3):
                record = {"model": self.model, "attempt": attempt + 1}
                attempts.append(record)
                try:
                    with observation(f"ASR 请求｜{self.model}｜{attempt + 1}", as_type="generation",
                                     model=self.model):
                        result = self._transcribe_normalized(normalized)
                        record["status"] = "success"
                        update_current(output={"status": "success", "model": self.model})
                    result.metadata.update(requested_model=self.model, model=self.model,
                                           asr_attempts=list(attempts))
                    return result
                except NoSpeechDetectedError as exc:
                    record["status"] = "no_speech"
                    exc.asr_metadata = {"requested_model": self.model, "model": self.model,
                                        "asr_attempts": list(attempts)}
                    raise
                except (HTTPException, RuntimeError, httpx.RequestError) as exc:
                    reason = self._retry_reason(exc)
                    record.update(status="failed", reason=reason or "non_retryable")
                    from app.services.asr_stream_service import ASRServiceError
                    if isinstance(exc, ASRServiceError):
                        record["diagnostic"] = exc.diagnostic
                        exc.asr_metadata = {"requested_model": self.model, "model": self.model,
                                            "asr_attempts": list(attempts)}
                    logger.warning("ASR attempt failed model=%s attempt=%d category=%s",
                                   self.model, attempt + 1, record["reason"])
                    if not reason or attempt == 2:
                        raise
                    time.sleep(attempt + 1)

    def _transcribe_normalized(self, file_path: str) -> TranscriptResult:
        bearer = self._recognition_bearer()
        policy = self._recorded_audio_policy(bearer)
        from app.services.adaptive_asr_policy import RecordingModelPolicy
        from app.services.meeting_model_boundary import meeting_execution, require_meeting_policy
        if meeting_execution.get():
            require_meeting_policy(policy)
        if isinstance(policy, RecordingModelPolicy):
            if "meeting" in policy.use_cases:
                if not policy.meeting_ready:
                    raise ValueError(f"{policy.meeting_blocked_reason}；尚未提交音频")
                try:
                    return self._transcribe_recording(file_path, bearer, policy)
                except Exception as error:
                    from app.services.asr_stream_service import ASRServiceError
                    if isinstance(error, (ASRServiceError, HTTPException, RuntimeError, httpx.RequestError)):
                        try:
                            error.asr_single_attempt = True
                        except AttributeError:
                            pass
                    raise
        return self._transcribe_stream(file_path)

    def _recorded_audio_policy(self, bearer):
        from app.services.adaptive_asr_policy import RecordingModelPolicy
        if self._policy_cache is not None and self._policy_cache[0] == bearer:
            return self._policy_cache[1]
        try:
            response = httpx.get(self.base_url + "/v1/models",
                headers={"Authorization": "Bearer " + bearer}, timeout=15, trust_env=False)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise ValueError("无法读取录音处理规则，尚未提交音频，请刷新服务状态") from None
        models = data.get("data", []) if isinstance(data, dict) else []
        if not isinstance(models, list):
            raise ValueError("模型目录格式无效，尚未提交音频")
        model = next((row for row in models if isinstance(row, dict)
                      and row.get("id") == self.model and row.get("modelType") == "asr"), None)
        if model is None:
            raise ValueError("当前服务未返回所选转写模型，尚未提交音频")
        policy = RecordingModelPolicy.from_capabilities(model.get("capabilities"))
        self._policy_cache = (bearer, policy)
        return policy

    @staticmethod
    def _recording_identity(file_path):
        digest = hashlib.sha256()
        with open(file_path, "rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _restore_recording_result(value):
        if not isinstance(value, dict) or not isinstance(value.get("full_text"), str) or not value["full_text"].strip():
            raise ValueError("已保存的会议转写无效，未重新提交音频")
        rows = value.get("segments")
        if not isinstance(rows, list) or not rows:
            raise ValueError("已保存的会议转写缺少时间轴，未重新提交音频")
        segments = []
        previous_end = 0.0
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("已保存的会议转写时间轴无效")
            start, end = row.get("start"), row.get("end")
            text = row.get("text")
            if (type(start) not in (int, float) or type(end) not in (int, float)
                    or not math.isfinite(start) or not math.isfinite(end)
                    or not 0 <= start < end or start < previous_end
                    or not isinstance(text, str) or not text.strip()):
                raise ValueError("已保存的会议转写时间轴无效")
            previous_end = end
            segments.append(TranscriptSegment(
                start=float(start), end=float(end), text=text,
                raw_text=row.get("raw_text") if isinstance(row.get("raw_text"), str) else text,
                cleaned_text=row.get("cleaned_text") if isinstance(row.get("cleaned_text"), str) else None,
                speaker_id=str(row["speaker_id"]) if row.get("speaker_id") is not None else None,
                speaker_label=row.get("speaker_label") if isinstance(row.get("speaker_label"), str) else None,
                timestamp_estimated=row.get("timestamp_estimated") is True,
            ))
        metadata = value.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("已保存的会议转写元数据无效")
        return TranscriptResult(
            language=value.get("language") if isinstance(value.get("language"), str) else None,
            full_text=value["full_text"], segments=segments, metadata=dict(metadata),
        )

    _RECORDING_JOB_STATES = {"created", "queued", "submitting", "processing",
                             "completed", "failed", "outcome_unknown"}

    @staticmethod
    def _load_recording_checkpoint(checkpoint_file):
        if not checkpoint_file.exists():
            return None
        try:
            if checkpoint_file.stat().st_size > 16 * 1024 * 1024:
                raise ValueError
            saved = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            raise ValueError("已保存的会议转写记录无法读取，未重新提交音频") from None
        if not isinstance(saved, dict) or saved.get("version") not in (1, 2):
            raise ValueError("已保存的会议转写记录无效，未重新提交音频")
        return saved

    @staticmethod
    def _validate_recording_job(saved, duration, size, stamp):
        job_id = saved.get("job_id")
        try:
            if str(uuid.UUID(str(job_id))) != str(job_id):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ValueError("已保存的会议转写任务无效，未重新提交音频") from None
        if saved.get("status") not in VILabTranscriber._RECORDING_JOB_STATES:
            raise ValueError("已保存的会议转写任务无效，未重新提交音频")
        if (saved.get("duration_seconds") != round(duration, 3)
                or saved.get("size_bytes") != size):
            raise ValueError("已保存的会议转写任务与当前音频不一致，未重新提交音频")
        if stamp is not None and saved.get("execution") != stamp:
            raise ValueError("本次处理的会议转写记录归属不一致")
        return job_id

    @staticmethod
    def _retry_after_seconds(response, fallback):
        try:
            value = float(response.headers.get("retry-after"))
        except (TypeError, ValueError):
            return fallback
        if not math.isfinite(value):
            return fallback
        return min(max(value, 2.0), 30.0)

    @staticmethod
    def _recording_job_wait_seconds():
        try:
            value = float(os.environ.get("VINOTE_ASR_JOB_WAIT_SECONDS", ""))
        except ValueError:
            value = 0.0
        return value if 60 <= value <= 24 * 3600 else 6 * 3600

    @staticmethod
    def _raise_recording_failure(checkpoint):
        from app.services.asr_stream_service import ASRServiceError
        error = checkpoint.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        if code in {"empty_result_unverified", "asr_empty_result"}:
            raise NoSpeechDetectedError("该音频片段未识别出文字")
        raise ASRServiceError(code if isinstance(code, str) and code else "asr_provider_error")

    def _recording_job_get(self, path, bearer):
        def get(token):
            headers = {"Authorization": "Bearer " + token} if token else {}
            return httpx.get(self.base_url + path, headers=headers,
                             timeout=httpx.Timeout(30, connect=15, pool=30),
                             trust_env=False, follow_redirects=False)

        response = get(bearer)
        if response.status_code in (401, 403) and self.cloud_user_id:
            current = self._recognition_bearer()
            if current and current != bearer:
                response = get(current)
        return response

    def _transcribe_recording(self, file_path: str, bearer, policy) -> TranscriptResult:
        from app.config import settings
        from app.services.asr_checkpoint_lock import checkpoint_lock
        from app.services.asr_execution_binding import current_execution
        from app.services.asr_stream_service import ASRServiceError
        import wave

        execution = current_execution()
        if execution is not None:
            execution.validate_model(self.cloud_user_id, self.base_url, self.model)
        with wave.open(file_path, "rb") as audio:
            if ((audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getcomptype())
                    != (16000, 1, 2, "NONE")):
                raise ValueError("录音格式尚不能安全核验，未提交音频")
            duration = audio.getnframes() / audio.getframerate()
        size = Path(file_path).stat().st_size
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("录音没有有效音频")
        if duration > policy.max_audio_seconds:
            raise ValueError("录音超过当前会议模型的时长上限，尚未提交音频")
        if size > policy.max_audio_bytes:
            raise ValueError("录音超过当前会议模型的大小上限，尚未提交音频")
        digest = self._recording_identity(file_path)
        owner = self.cloud_user_id or hashlib.sha256(self.api_key.encode()).hexdigest()
        stamp = None
        if execution is not None:
            stamp = {**execution.stamp(), "normalized_identity": digest}
            folder = execution.chunks / "vilab_recording"
            for path in (execution.chunks, folder.parent, folder):
                if path.is_symlink() or path.resolve() != path:
                    raise ValueError("本次处理的转写目录无法核验")
        else:
            identity = hashlib.sha256(json.dumps(
                [self.base_url, owner, self.model, digest], ensure_ascii=False).encode()).hexdigest()
            folder = Path(settings.data_dir) / "asr-recording-checkpoints" / identity
        folder.mkdir(parents=True, exist_ok=True)
        checkpoint_file = folder / "meeting.json"
        if checkpoint_file.is_symlink():
            raise ValueError("会议转写记录位置无效，未提交音频")
        with checkpoint_lock(folder):
            saved = self._load_recording_checkpoint(checkpoint_file)
            if saved is not None:
                status = saved.get("status")
                if saved.get("version") == 1:
                    if stamp is not None and saved.get("execution") != stamp:
                        raise ValueError("本次处理的会议转写记录归属不一致")
                    if status == "completed":
                        return self._restore_recording_result(saved.get("result"))
                    if status != "inflight":
                        raise ValueError("已保存的会议转写状态无效，未重新提交音频")
                    # A synchronous submission without a job id can never be replayed.
                    raise ASRServiceError("unknown_result")
                job_id = self._validate_recording_job(saved, duration, size, stamp)
                if saved.get("model") != self.model:
                    raise ValueError("已保存的会议转写任务与当前模型不一致，未重新提交音频")
                if status == "completed":
                    if "result" not in saved:
                        return self._finish_recording_job(job_id, saved, checkpoint_file, file_path, bearer)
                    return self._restore_recording_result(saved["result"])
                if status == "outcome_unknown":
                    raise ASRServiceError("unknown_result")
                if status == "failed":
                    self._raise_recording_failure(saved)
                if status != "created":
                    return self._await_recording_job(job_id, saved, checkpoint_file, file_path, bearer)
            else:
                job_id = str(uuid.uuid4())
                saved = {"version": 2, "status": "created", "job_id": job_id,
                         "idempotency_key": job_id, "model": self.model,
                         "duration_seconds": round(duration, 3), "size_bytes": size}
                if stamp is not None:
                    saved["execution"] = stamp
                # Durable before dispatch: a lost response resumes the same job.
                _save_checkpoint(checkpoint_file, saved)
            return self._submit_recording_job(job_id, saved, checkpoint_file, file_path, bearer)

    def _submit_recording_job(self, job_id, checkpoint, checkpoint_file, file_path, bearer):
        from app.services.asr_stream_service import ASRServiceError
        fields = {"mode": "meeting"}
        if self.model:
            fields["model"] = self.model
        if self.language:
            fields["language"] = self.language
        headers = {"Idempotency-Key": job_id}
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        # The read budget covers upload acknowledgement only; recognition is
        # tracked separately by polling the created job.
        timeout = httpx.Timeout(120, connect=15, write=600, pool=30)
        try:
            with Path(file_path).open("rb") as audio:
                response = httpx.post(
                    self.base_url + "/v1/asr/transcription-jobs", headers=headers,
                    files={"file": (Path(file_path).name, audio, "audio/wav")},
                    data=fields, timeout=timeout, trust_env=False, follow_redirects=False,
                )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, httpx.RequestError):
            # The same idempotency key resolves the job without a second submission.
            raise ASRServiceError("unknown_result") from None
        if not response.is_success:
            code = None
            try:
                error = response.json().get("error")
                code = error.get("code") if isinstance(error, dict) else None
            except (ValueError, AttributeError):
                pass
            if code == "meeting_audio_delivery_unavailable":
                checkpoint_file.unlink(missing_ok=True)
                raise HTTPException(503, "当前公网服务没有可被语音服务访问的音频地址，会议转写暂不可用；实时转写不受影响。")
            if 400 <= response.status_code < 500:
                checkpoint_file.unlink(missing_ok=True)
                raise RuntimeError(f"VILab STT returned HTTP {response.status_code}")
            raise ASRServiceError("unknown_result")
        try:
            payload = response.json()
        except ValueError:
            raise ASRServiceError("unknown_result") from None
        status = payload.get("status") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or payload.get("id") != job_id \
                or status not in self._RECORDING_JOB_STATES:
            raise ASRServiceError("unknown_result")
        if status != checkpoint.get("status"):
            checkpoint["status"] = status
            _save_checkpoint(checkpoint_file, checkpoint)
        if status == "completed":
            return self._finish_recording_job(job_id, checkpoint, checkpoint_file, file_path, bearer)
        if status == "outcome_unknown":
            raise ASRServiceError("unknown_result")
        if status == "failed":
            self._raise_recording_failure(checkpoint)
        return self._await_recording_job(job_id, checkpoint, checkpoint_file, file_path, bearer)

    def _await_recording_job(self, job_id, checkpoint, checkpoint_file, file_path, bearer):
        from app.services.asr_stream_service import ASRServiceError
        deadline = time.monotonic() + self._recording_job_wait_seconds()
        delay = 5.0
        while True:
            try:
                response = self._recording_job_get(
                    f"/v1/asr/transcription-jobs/{job_id}", bearer)
            except httpx.RequestError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ASRServiceError("unknown_result") from None
                time.sleep(min(delay, remaining))
                continue
            if response.status_code in (401, 403):
                raise ASRServiceError("auth_failed")
            if response.status_code == 404:
                raise ASRServiceError("unknown_result")
            if response.status_code == 429 or response.status_code >= 500:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ASRServiceError("unknown_result")
                time.sleep(min(self._retry_after_seconds(response, delay), remaining))
                delay = min(delay * 2, 30)
                continue
            if not response.is_success:
                raise ASRServiceError("unknown_result")
            try:
                payload = response.json()
            except ValueError:
                raise ASRServiceError("unknown_result") from None
            status = payload.get("status") if isinstance(payload, dict) else None
            if status not in self._RECORDING_JOB_STATES:
                raise ASRServiceError("unknown_result")
            if status != checkpoint.get("status"):
                checkpoint["status"] = status
                error = payload.get("error")
                if status == "failed" and isinstance(error, dict):
                    checkpoint["error"] = {"code": error.get("code"), "message": error.get("message")}
                elif status != "failed":
                    checkpoint.pop("error", None)
                _save_checkpoint(checkpoint_file, checkpoint)
            if status == "completed":
                return self._finish_recording_job(job_id, checkpoint, checkpoint_file, file_path, bearer)
            if status == "failed":
                self._raise_recording_failure(checkpoint)
            if status == "outcome_unknown":
                raise ASRServiceError("unknown_result")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ASRServiceError("unknown_result")
            time.sleep(min(self._retry_after_seconds(response, delay), remaining))

    def _finish_recording_job(self, job_id, checkpoint, checkpoint_file, file_path, bearer):
        from app.services.asr_stream_service import ASRServiceError
        response = None
        for attempt in range(3):
            try:
                response = self._recording_job_get(
                    f"/v1/asr/transcription-jobs/{job_id}/result", bearer)
                break
            except httpx.RequestError:
                if attempt == 2:
                    raise ASRServiceError("unknown_result") from None
                time.sleep(attempt + 1)
        if response.status_code in (401, 403):
            raise ASRServiceError("auth_failed")
        if response.status_code == 409:
            try:
                error = response.json().get("error")
            except (ValueError, AttributeError):
                error = None
            if isinstance(error, dict) and error.get("jobStatus") == "failed":
                checkpoint["status"] = "failed"
                checkpoint["error"] = {"code": error.get("code"), "message": error.get("message")}
                _save_checkpoint(checkpoint_file, checkpoint)
                self._raise_recording_failure(checkpoint)
        if not response.is_success:
            raise ASRServiceError("unknown_result")
        try:
            payload = response.json()
            result = self._result(payload, file_path, transport="recording")
        except NoSpeechDetectedError:
            checkpoint["status"] = "failed"
            checkpoint["error"] = {"code": "empty_result_unverified"}
            _save_checkpoint(checkpoint_file, checkpoint)
            raise
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ASRServiceError("unknown_result") from None
        completed = dict(checkpoint)
        completed.update(status="completed", result=asdict(result))
        completed.pop("error", None)
        _save_checkpoint(checkpoint_file, completed)
        return result

    def _transcribe_stream(self, file_path: str) -> TranscriptResult:
        from app.config import settings
        from app.services.asr_checkpoint_lock import checkpoint_lock
        from app.services.asr_stream_service import ASRServiceError
        from app.services.asr_execution_binding import current_execution
        import wave

        execution = current_execution()
        if execution is not None:
            execution.validate_model(self.cloud_user_id, self.base_url, self.model)
        bearer = self.api_key
        with wave.open(file_path, "rb") as audio:
            if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getcomptype()) != (16000, 1, 2, 'NONE'):
                raise ValueError('录音格式尚不能安全核验，未提交音频')
            duration = audio.getnframes() / audio.getframerate()
            total_frames = audio.getnframes()
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("录音没有有效音频")
        identity = hashlib.sha256()
        cache_owner = self.cloud_user_id or hashlib.sha256(self.api_key.encode()).hexdigest()
        identity.update(json.dumps([self.base_url, cache_owner, self.model], ensure_ascii=False).encode())
        with open(file_path, "rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                identity.update(block)
        digest = identity.hexdigest()
        donor = Path(settings.data_dir) / 'asr-stream-checkpoints' / digest
        folder = donor
        stamp = None
        if execution is not None:
            stamp = {**execution.stamp(), 'normalized_identity': digest}
            # One fixed directory per operation. A different normalized identity
            # must fail its stamp check, never escape a prior inflight by path.
            folder = execution.chunks / 'vilab_stream'
            # No path supplied by a request can redirect checkpoint writes.
            for path in (execution.chunks, folder.parent, folder):
                if path.is_symlink() or path.resolve() != path:
                    raise ValueError('本次处理的转写目录无法核验')
        folder.mkdir(parents=True, exist_ok=True)
        with checkpoint_lock(folder), ExitStack() as locks:
            # A previous-version process may still own this sentinel, or have
            # died after dispatch. Neither the new OS lock nor a complete cache
            # authorizes removing it or replaying its request.
            legacy_lock = folder / "recognition.lock"
            if legacy_lock.exists() or legacy_lock.is_symlink():
                raise ASRServiceError("unknown_result")
            if execution is not None:
                checkpoint = folder / 'recognition.json'
                saved = None
                if checkpoint.exists() or checkpoint.is_symlink():
                    if checkpoint.is_symlink():
                        raise ValueError('本次处理的转写记录无法核验')
                    saved = json.loads(checkpoint.read_text(encoding='utf-8'))
                    if not isinstance(saved, dict) or saved.get('execution') != stamp:
                        raise ValueError('本次处理的转写记录归属不一致')
                    if execution.fresh and 'seed' in saved:
                        raise _CheckpointEvidenceUnavailable()
                    if saved.get('inflight') is not None:
                        raise ASRServiceError('unknown_result')
                    confirmed = _confirmed_prefix(saved, total_frames)
                    if confirmed and saved['completed'][-1]['end'] == duration:
                        # A verified complete child is self-contained. Donor
                        # availability only gates seeding or remaining sends.
                        return self._transcribe_checkpoint(file_path, bearer, duration, total_frames, folder)
                if execution.fresh:
                    # A separately accepted fresh operation starts at zero. Do
                    # not even lock/read a legacy global or selected-parent
                    # donor; its inflight/prefix belongs to the old operation.
                    if saved is None:
                        _save_checkpoint(checkpoint, {'completed': [], 'execution': stamp})
                    return self._transcribe_checkpoint(file_path, bearer, duration, total_frames, folder)
                # Keep the same-source lock for the entire new execution, not
                # just the donor read. Legacy and new operations cannot race
                # into paid submissions after the seed has been read.
                if donor.is_symlink() or donor.parent.is_symlink():
                    raise _CheckpointEvidenceUnavailable()
                try:
                    donor.mkdir(parents=True, exist_ok=True)
                    locks.enter_context(checkpoint_lock(donor))
                except (OSError, ValueError):
                    raise _CheckpointEvidenceUnavailable() from None
                parts, donor_hash = _read_donor(donor, total_frames)
                parent_seed = None
                if execution.canonical is not None:
                    from app.services.parent_asr_prefix import locked_parent_prefix
                    from app.services.task_artifact_service import TaskArtifactService
                    parent_seed = locks.enter_context(locked_parent_prefix(
                        execution._receipts, TaskArtifactService(settings.output_dir),
                        owner=execution.owner, task_id=execution.task,
                        normalized_identity=digest, total_frames=total_frames,
                        expected_prefix=json.loads(execution.parent_prefix_json)))
                    parts = parent_seed['completed']
                    if saved is not None and (saved.get('seed') != parent_seed['seed']
                            or confirmed[:len(parts)] != parts):
                        raise _CheckpointEvidenceUnavailable()
                if saved is None:
                    seeded = {'completed': parts, 'execution': stamp}
                    if parent_seed is not None:
                        seeded['seed'] = parent_seed['seed']
                    elif parts:
                        seeded['seed'] = {'version': 1, 'donor_identity': digest,
                                          'checkpoint_sha256': donor_hash,
                                          'confirmed_end_frame': round(parts[-1]['end'] * 16000)}
                    # Even an empty seed is persisted. No in-memory handoff can
                    # accidentally submit a plan before the evidence is durable.
                    _save_checkpoint(checkpoint, seeded)
            return self._transcribe_checkpoint(file_path, bearer, duration, total_frames, folder)

    def _recognition_bearer(self):
        if self.cloud_user_id:
            from app.services.vilab_cloud_service import VILabCloudService
            headers = VILabCloudService().authorization(self.cloud_user_id, self.base_url, self.cloud_connection_id,
                                                       self.cloud_connection_auth_mode)
            return headers.get("Authorization", "").removeprefix("Bearer ")
        return self.api_key

    def _transcribe_checkpoint(self, file_path, bearer, duration, total_frames, folder):
        from app.services.asr_stream_service import ASRServiceError, recognize_pcm
        from app.services.adaptive_asr_policy import plan_intervals
        checkpoint_file = folder / "recognition.json"
        try:
            checkpoint = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            checkpoint = {"completed": []}
        except (ValueError, OSError):
            raise ValueError("已保存的转写记录无法读取，未重新提交音频") from None
        if not isinstance(checkpoint, dict) or not isinstance(checkpoint.get("completed"), list):
            raise ValueError("已保存的转写记录无效，未重新提交音频")
        if checkpoint.get("inflight") is not None:
            raise ASRServiceError("unknown_result")
        # Preserve legacy evidence, including invalid records, rather than
        # silently replacing a historical request layout.
        from app.services.asr_stream_service import valid_duration_limit
        if checkpoint.get("session_limit") is not None and not valid_duration_limit(checkpoint["session_limit"]):
            raise ValueError("识别服务会话记录无效，原录音保留")
        parts = checkpoint["completed"]
        previous = 0.0
        for part in parts:
            if (not isinstance(part, dict) or part.get("start") != previous
                    or type(part.get("end")) not in (float, int) or not math.isfinite(part["end"])
                    or not previous < part["end"] <= duration or not isinstance(part.get("text"), str)):
                raise ValueError("已保存的转写进度不完整，原录音保留，未继续提交")
            previous = part["end"]
            _empty_terminal_fields(part)
        start = parts[-1]["end"] if parts else 0
        if start and self.progress_callback:
            # This is saved confirmed coverage, never a new partial/final event.
            self.progress_callback(start, duration, start)

        def save():
            _save_checkpoint(checkpoint_file, checkpoint)

        if start < duration:
            plan = checkpoint.get("plan")
            if plan is None:
                bearer = self._recognition_bearer()
                policy = self._recorded_audio_policy(bearer)
                intervals = plan_intervals(file_path, policy, start_frame=round(start * 16000))
                plan = checkpoint["plan"] = {"version": 1,
                    "max_session_audio_bytes": policy.max_session_audio_bytes,
                    "intervals": [list(pair) for pair in intervals]}
                save()
            intervals = plan.get("intervals") if isinstance(plan, dict) else None
            budget = plan.get("max_session_audio_bytes") if isinstance(plan, dict) else None
            if (not isinstance(plan, dict) or plan.get("version") != 1 or type(budget) is not int or budget % 2
                    or not 640 <= budget <= 64 * 1024 * 1024 or not isinstance(intervals, list)):
                raise ValueError("已保存的录音分段规则无效，未提交音频")
            cursor = None
            for pair in intervals:
                if (not isinstance(pair, list) or len(pair) != 2
                        or any(type(frame) is not int for frame in pair)
                        or not 0 <= pair[0] < pair[1] <= total_frames
                        or (pair[1] - pair[0]) * 2 > budget
                        or cursor is not None and pair[0] != cursor):
                    raise ValueError("已保存的录音分段位置无效，未提交音频")
                cursor = pair[1]
            remaining = [pair for pair in intervals if pair[1] > round(start * 16000)]
            if not remaining or remaining[0][0] != round(start * 16000) or cursor != total_frames:
                raise ValueError("已保存的录音分段不完整，未提交音频")
        else:
            remaining = []
        for first_frame, end_frame in remaining:
            start, end = first_frame / 16000, end_frame / 16000
            bearer = self._recognition_bearer()
            # Persist before dispatch: interruption can never silently replay
            # this interval. A final and the cleared marker are committed together.
            checkpoint["inflight"] = {"start_frame": first_frame, "end_frame": end_frame}
            save()
            try:
                payload = recognize_pcm(self.base_url, bearer, self.model, file_path, start=start, end=end,
                    progress=(lambda received, _total: self.progress_callback(start + received, duration, start))
                    if self.progress_callback else None)
            except Exception as error:
                # Preserve an explicit provider error; transport ambiguity has
                # no automatic replay authorization. The durable marker remains.
                if self._retry_reason(error):
                    # recognize_pcm only permits this classification before
                    # any binary audio attempt. A failed handshake is not replay.
                    checkpoint.pop("inflight", None)
                    save()
                    raise
                if isinstance(error, ASRServiceError):
                    error.retry_reason = None
                    raise
                raise ASRServiceError("unknown_result") from None
            confirmed_segments = []
            for item in payload.get("segments") or []:
                if not isinstance(item, dict):
                    confirmed_segments = []
                    break
                try:
                    offset_start, offset_end = float(item["start"]), float(item["end"])
                    segment_text = item["text"]
                    if (not math.isfinite(offset_start) or not math.isfinite(offset_end)
                            or not 0 <= offset_start < offset_end <= end - start
                            or not isinstance(segment_text, str) or not segment_text.strip()):
                        raise ValueError("Invalid timestamp evidence")
                    confirmed_segments.append({"start": start + offset_start, "end": start + offset_end,
                                               "text": segment_text})
                except (KeyError, TypeError, ValueError):
                    confirmed_segments = []
                    break
            # Don't discard final text to retain incomplete provider segments.
            if "".join("".join(s["text"].split()) for s in confirmed_segments) != "".join(payload["text"].split()):
                confirmed_segments = []
            parts.append({"start": start, "end": end, "text": payload["text"], "language": payload.get("language"),
                          "segments": confirmed_segments, **_empty_terminal_fields(payload)})
            checkpoint.pop("inflight", None)
            save()
            start = end
            if self.progress_callback:
                self.progress_callback(start, duration, start)
        text = "\n".join(part["text"] for part in parts if part["text"])
        if not text:
            raise NoSpeechDetectedError("该录音未识别出文字")
        segments = []
        for part in parts:
            if part.get("segments"):
                segments.extend(TranscriptSegment(start=s["start"], end=s["end"], text=s["text"],
                    raw_text=s["text"], timestamp_estimated=False) for s in part["segments"])
            elif part["text"]:
                segments.append(TranscriptSegment(start=part["start"], end=part["end"], text=part["text"],
                    raw_text=part["text"], timestamp_estimated=True))
        return TranscriptResult(language=next((p["language"] for p in parts if p["language"]), self.language),
            full_text=text, segments=segments,
            metadata={"provider": self.provider, "model": self.model, "transport": "websocket",
                      "timestamp_granularity": "session" if all(s.timestamp_estimated for s in segments) else
                        "segment" if all(not s.timestamp_estimated for s in segments) else "mixed",
                      "session_count": len(parts),
                      "unrecognized_segments": [{"start": p["start"], "end": p["end"],
                          "reason": p.get("recognition_outcome", "empty_recognition")}
                          for p in parts if not p["text"]]})

    def _transcribe_http(self, file_path: str) -> TranscriptResult:
        # Streaming ASR may consume the upload at real-time speed.
        duration = float(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path,
        ], text=True, timeout=30).strip())
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("ASR 音频时长超出分块范围，请重新分块")
        # Compatibility HTTP path only; normal recording requests use the
        # catalog policy and adaptive PCM intervals above. Retain a bounded
        # duration-based read deadline for explicit legacy HTTP callers.
        timeout = httpx.Timeout(max(90, duration * 1.5 + 60), connect=10)
        fields = {}
        if self.model:
            fields["model"] = self.model
        if self.language:
            fields["language"] = self.language
        if self.cloud_user_id:
            from app.services.vilab_cloud_service import VILabCloudService

            service = VILabCloudService()
            frozen = {"mode": "cloud", "configured": True, "server_url": self.base_url,
                      "asr_model": self.model, "llm_model": "",
                      **({"connection_id": self.cloud_connection_id} if self.cloud_connection_id else {}),
                      **({"connection_auth_mode": self.cloud_connection_auth_mode} if self.cloud_connection_auth_mode else {})}
            with service.task_snapshot(self.cloud_user_id, snapshot=frozen), Path(file_path).open("rb") as audio:
                payload = service.request(self.cloud_user_id, "POST", "/v1/asr/transcriptions",
                    files={"file": (Path(file_path).name, audio, "audio/wav")}, data=fields, timeout=timeout)
            return self._result(payload, file_path)
        with Path(file_path).open("rb") as audio:
            try:
                response = httpx.post(
                    f"{self.base_url}/v1/asr/transcriptions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"file": (Path(file_path).name, audio, "audio/wav")},
                    data=fields, timeout=timeout,
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                raise RuntimeError("VILab STT connection failed or timed out") from None
        if not response.is_success:
            if response.status_code in {502, 503}:
                try:
                    error = response.json().get("error")
                    message = error.get("message") if isinstance(error, dict) else error
                except (ValueError, AttributeError):
                    message = None
                if response.status_code == 502 and message in {
                    "Aliyun ASR returned an empty transcript.",
                    "Volcengine ASR returned an empty transcript.",
                }:
                    raise NoSpeechDetectedError("该音频片段未识别出文字")
                if message == "Account authentication is temporarily unavailable":
                    raise HTTPException(503, "云端账号认证服务暂时不可用，请稍后重试")
            # Do not echo upstream bodies: they may contain credentials.
            raise RuntimeError(f"VILab STT returned HTTP {response.status_code}")
        return self._result(response.json(), file_path)

    def _result(self, payload, file_path, *, transport=None):
        if isinstance(payload, dict) and isinstance(payload.get("text"), str) and not payload["text"].strip():
            # A successful explicit empty recognition is also evidence of an
            # unrecognized interval. Malformed/missing fields still fail below.
            if not payload.get("segments"):
                raise NoSpeechDetectedError("该音频片段未识别出文字")
        text = str(payload.get("text") or "").strip()
        if not text:
            raise RuntimeError("VILab STT returned an empty transcript")
        duration = float(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path,
        ], text=True, timeout=30).strip())
        # Preserve provider evidence when available; never synthesize speakers.
        segments = []
        for item in payload.get("segments") or []:
            if not isinstance(item, dict) or not str(item.get("text") or "").strip():
                continue
            try:
                start, end = float(item["start"]), float(item["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if not 0 <= start <= end <= duration + 1:
                continue
            speaker = item.get("speakerId", item.get("speaker_id", item.get("speaker")))
            label = item.get("speakerLabel", item.get("speaker_label"))
            evidence = item.get("speakerEvidence", item.get("speaker_evidence"))
            segments.append(TranscriptSegment(
                start=start, end=end, text=str(item["text"]), raw_text=str(item["text"]),
                speaker_id=str(speaker) if speaker is not None else None,
                speaker_label=str(label) if label is not None else None,
                speaker_evidence=evidence if isinstance(evidence, list) else [],
                timestamp_estimated=False,
            ))
        has_timestamps = bool(segments)
        if not segments:
            segments = [TranscriptSegment(start=0, end=duration, text=text, raw_text=text,
                                          timestamp_estimated=True)]
        speaker_evidence = any(segment.speaker_id is not None for segment in segments)
        metadata = {
            "provider": "vilab-server",
            "timestamp_granularity": "segment" if has_timestamps else "file",
            "speaker_diarization": speaker_evidence,
        }
        if transport == "recording":
            metadata["model_speaker_diarization"] = speaker_evidence
        if transport:
            metadata["transport"] = transport
        return TranscriptResult(
            language=payload.get("language") or self.language,
            full_text=text,
            segments=segments,
            metadata=metadata,
        )
