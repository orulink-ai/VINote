"""One disposable spawned native inference process; no account data crosses IPC."""
from __future__ import annotations

import ctypes
from dataclasses import asdict
import json
import math
import multiprocessing
import os
from pathlib import Path
import queue
import re
import signal
import struct
import threading
import time

_WORKER_SLOT = threading.BoundedSemaphore(1)
_MAX_RESULT_BYTES = 32 * 1024 * 1024


def _windows_job(pid):
    """Kill the worker on abrupt backend exit, including Uvicorn reload."""
    if os.name != "nt":
        return None
    from ctypes import wintypes
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    api.CreateJobObjectW.restype = wintypes.HANDLE
    api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    job = api.CreateJobObjectW(None, None)
    # JOBOBJECT_EXTENDED_LIMIT_INFORMATION: LimitFlags at offset 16 on both ABIs.
    info = ctypes.create_string_buffer(144 if struct.calcsize("P") == 8 else 112)
    struct.pack_into("I", info, 16, 0x2000)  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    handle = api.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE
    try:
        if not job or not handle or not api.SetInformationJobObject(job, 9, info, len(info)) or not api.AssignProcessToJobObject(job, handle):
            raise OSError("无法为说话人分析创建进程清理保护")
    except BaseException:
        if job:
            api.CloseHandle(job)
        raise
    finally:
        if handle:
            api.CloseHandle(handle)
    return job, api


def _parent_guard(parent_pid):
    if os.name == "posix" and hasattr(signal, "SIGKILL"):
        # Linux workers must not outlive a replaced API worker.
        import sys
        if sys.platform.startswith("linux"):
            libc = ctypes.CDLL(None)
            if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
                raise RuntimeError("无法保护说话人子进程")
            if os.getppid() != parent_pid:
                raise RuntimeError("说话人分析的父进程已退出")


def _infer(request, progress, parent_pid):
    _parent_guard(parent_pid)
    import numpy as np
    import sherpa_onnx
    from app.services.speaker_diarization_service import build_speaker_turns
    from app.services.speaker_clustering_service import refine_speaker_turns

    root = Path(request["folder"])
    samples = np.memmap(root / "audio.f32", dtype="float32", mode="r")
    engine = None

    def report(stage, fraction):
        try:
            progress.put_nowait((stage, fraction))
        except queue.Full:
            pass  # Native inference must never wait for the parent/UI.

    try:
        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=request["segmentation"]),
                num_threads=2),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=request["embedding"], num_threads=2),
            clustering=sherpa_onnx.FastClusteringConfig(num_clusters=request["speaker_count"] or -1,
                                                      threshold=request["threshold"]),
            min_duration_on=0.3, min_duration_off=0.5)
        if not config.validate():
            raise ValueError("Invalid speaker model configuration")
        engine = sherpa_onnx.OfflineSpeakerDiarization(config)
        last = -1

        def callback(done, total):
            nonlocal last
            fraction = min(1.0, done / max(total, 1))
            step = int(fraction * 20)
            if step != last:
                report("detection", fraction)
                last = step
            return 0

        detected = engine.process(samples, callback=callback).sort_by_start_time()
        del engine
        engine = None
        duration = len(samples) / 16000
        turns = build_speaker_turns(detected, duration)
        del detected
        if not turns:
            raise ValueError("No speaker turns")
        clustering = {"method": "fixed-speaker-count", "requested_count": request["speaker_count"]}
        if request["speaker_count"] is None:
            report("refinement", 1.0)
            turns, clustering = refine_speaker_turns(turns, samples, Path(request["embedding"]))
        payload = json.dumps({"protocol": 1, "duration": duration,
                              "turns": [asdict(turn) for turn in turns], "clustering": clustering}, allow_nan=False)
        if len(payload.encode("utf-8")) > _MAX_RESULT_BYTES:
            raise ValueError("Speaker result exceeds bound")
        temporary = root / "speaker-result.tmp"
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, root / "speaker-result.json")
    finally:
        del engine
        samples._mmap.close()


def _worker(request, progress, parent_pid):
    try:
        _infer(request, progress, parent_pid)
    except BaseException:
        # Neither exception text nor native/provider output is an IPC payload.
        raise SystemExit(1) from None


def validate_result(value, duration):
    from app.services.speaker_diarization_service import SpeakerTurn
    if not isinstance(value, dict) or value.get("protocol") != 1 or value.get("duration") != duration:
        raise ValueError("说话人分析结果与当前录音不匹配")
    raw = value.get("turns")
    if not isinstance(raw, list) or not raw or len(raw) > 200000 or not isinstance(value.get("clustering"), dict):
        raise ValueError("说话人分析结果无效")
    turns = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"start", "end", "speaker_id"}:
            raise ValueError("说话人分析区间无效")
        start, end, speaker = item["start"], item["end"], item["speaker_id"]
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end <= duration
                or not isinstance(speaker, str) or not re.fullmatch(r"speaker_(?:[1-9][0-9]*|unknown|overlap)", speaker)
                or turns and start < turns[-1].end):
            raise ValueError("说话人分析区间无效")
        turns.append(SpeakerTurn(start, end, speaker))
    return turns, value["clustering"]


def run_speaker_worker(pcm_path, segmentation, embedding, speaker_count, threshold,
                       progress=None, timeout_seconds=None):
    """Internal trusted paths only. The worker never writes permanent evidence."""
    pcm_path = Path(pcm_path).resolve(strict=True)
    if pcm_path.name != "audio.f32" or pcm_path.stat().st_size % 4 or pcm_path.stat().st_size < 4:
        raise ValueError("说话人分析音频格式无效")
    segmentation = Path(segmentation).resolve(strict=True)
    embedding = Path(embedding).resolve(strict=True)
    if speaker_count is not None and (type(speaker_count) is not int or not 1 <= speaker_count <= 20):
        raise ValueError("说话人人数无效")
    if not math.isfinite(threshold) or not 0 < threshold <= 2:
        raise ValueError("说话人聚类阈值无效")
    duration = pcm_path.stat().st_size / (4 * 16000)
    timeout = timeout_seconds if timeout_seconds is not None else max(300.0, duration * 12 + 300)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("说话人分析超时配置无效")
    result_path = pcm_path.parent / "speaker-result.json"
    request = {"folder": str(pcm_path.parent), "segmentation": str(segmentation), "embedding": str(embedding),
               "speaker_count": speaker_count, "threshold": threshold}
    with _WORKER_SLOT:
        result_path.unlink(missing_ok=True)
        context = multiprocessing.get_context("spawn")
        events = context.Queue(maxsize=8)
        process = context.Process(target=_worker, args=(request, events, os.getpid()), daemon=True)
        job = None
        started = False
        try:
            process.start()
            started = True
            job = _windows_job(process.pid)
            deadline = time.monotonic() + timeout
            while process.is_alive():
                if time.monotonic() >= deadline:
                    raise TimeoutError("说话人分析超时，原件保留，可重试")
                try:
                    stage, fraction = events.get(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
                    if stage not in {"detection", "refinement"} or not math.isfinite(fraction) or not 0 <= fraction <= 1:
                        raise ValueError("说话人分析进度无效")
                    if progress:
                        progress(stage, fraction)
                except queue.Empty:
                    pass
            process.join(timeout=5)
            if process.exitcode != 0:
                raise RuntimeError("说话人分析进程异常退出，未保存无效结果，原件保留")
            if not result_path.is_file() or result_path.stat().st_size > _MAX_RESULT_BYTES:
                raise ValueError("说话人分析未返回有效结果")
            value = json.loads(result_path.read_text(encoding="utf-8"))
            return validate_result(value, duration)
        finally:
            if started:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=5)
                process.close()
            if job:
                job[1].CloseHandle(job[0])
            events.cancel_join_thread()
            events.close()
            result_path.unlink(missing_ok=True)
            (pcm_path.parent / "speaker-result.tmp").unlink(missing_ok=True)
