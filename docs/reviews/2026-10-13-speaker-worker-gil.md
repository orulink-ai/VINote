# Speaker worker GIL isolation verification

## Confirmed source evidence

Installed sherpa-onnx metadata reports 1.13.8. The matching upstream binding at
https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/sherpa-onnx/python/csrc/offline-speaker-diarization.cc
calls native `Process` without releasing the GIL, converting the full input to a
by-value `std::vector<float>`. This was source inspection, not binary disassembly.
The same version's embedding extractor explicitly releases the GIL; the primary
lock boundary is whole-recording detection.

The original VINote implementation ran native detection in the API process while
ASR sending and interface handling also required its GIL. VILab ends a session
after five minutes without audio, and its command queue holds 256 frames. These
provide plausible downstream failure paths. Existing task logs do not establish
the close code or attribute unrelated server sessions to this task.

## Applied implementation

`app/services/speaker_worker.py` uses explicit multiprocessing spawn, a single
backend-local worker slot, a disk-backed PCM input, and a nonblocking progress
queue limited to eight events. Detection and automatic refinement run in the
child; detection models are released before refinement, and process exit releases
remaining native state. Worker death, timeout, and callback cancellation fail the
operation and reap the worker. Timeout scales with recording duration; it is not
a provider/model recording-length limit.

Windows Job Objects terminate workers when the backend exits, including abrupt
replacement. Linux workers request a parent-death signal. The existing frozen
desktop entry invokes `freeze_support()` before app setup, and packaging collects
app submodules; no shell/module runner path is supplied by requests.

IPC receives only internal PCM/model paths and numeric configuration, without
account identifiers, credentials or transcript bodies. Temporary results have a
32 MiB size bound. The parent checks protocol, duration, interval ordering,
speaker labels and source/model identity, then writes permanent evidence using
the existing atomic save. A validated existing cache is reused without rewriting;
ASR failure after successful speaker analysis preserves that evidence.

The parent's `data/asr-sender-pacing.patch` was applied in the same source batch:
PCM packets wait individually, avoiding a catch-up burst after scheduler stalls.
Backend source edits have ended; the parent was notified before starting its
50-minute retry. Subsequent work here is tests, scripts and documentation only.

## Actual execution evidence

These are CLI/native-library observations, not Desktop UI acceptance:

| Check | Result |
| --- | --- |
| Short real model, old in-process boundary | Heartbeat target 0.05 s; maximum gap 0.560 s; elapsed 1.341 s |
| Same short audio, isolated worker | Maximum gap 0.051 s; elapsed 2.832 s; real detection and refinement completed |
| 20-second real model, isolated worker | Maximum gap 0.051 s; 102 beats; elapsed 5.195 s; detection and refinement completed; zero remaining worker children; empty stderr |
| Latest 20-second real model rerun | Maximum parent gap 0.051 s; 117 beats; elapsed 5.946 s; real detection and refinement completed; zero remaining worker children; exit 0 |
| Focused regression | 35 passed, one ordinary pytest process; includes pacing, malformed/stale evidence, cache reuse after ASR failure, callback cleanup, plus actual spawned process timeout/death cleanup without models |

No cloud ASR or LLM was invoked by the heartbeat runs. A 340-second diagnostic
invocation failed during model configuration validation before opening an ASR
session. Following the parent's updated instruction, no fresh 340-second ASR
test was started. The parent owns native recovery and the full original retry.

Reproduce the no-cloud real model check from the repository root:

```powershell
.venv/Scripts/python.exe scripts/check_speaker_worker_heartbeat.py --source data/asr-diagnostic-30s.wav --seconds 20
.venv/Scripts/python.exe -m pytest tests/test_speaker_worker.py tests/test_speaker_diarization.py tests/test_asr_stream.py -q -p no:cacheprovider
```

Ignored evidence files: `data/speaker-worker-heartbeat-short.jsonl`,
`data/speaker-worker-heartbeat-baseline.jsonl`,
`data/speaker-worker-heartbeat-20.jsonl` and corresponding stderr logs.
Diagnostic output contains timings/counts and optional sanitized failure/close
codes, never recognized text, credentials or raw provider messages.

## Remaining limits

2026-10-14 around 00:00 (Asia/Shanghai), the parent reports actual Desktop native
confirmation of the original 50-minute task: displayed Aliyun/Luna matched its
original selection and the user clicked recovery. The same task is now in ASR
with speaker evidence already cached. This is reported device evidence, not a
new probe run by this agent; there is no completed full transcript, LLM result
or saved-note acceptance yet. Backend edits/reloads are prohibited throughout
this run; no second cloud ASR has been started by this agent.

Full 3036-second retry success, UI polling responsiveness during that retry,
cross-platform execution and the actual frozen Windows release executable have
not been verified by this agent. The short test establishes restored parent
thread scheduling during real native inference; it does not prove every previous
network failure's peer/proxy close cause. Native inference still copies the full
input internally, so process isolation does not eliminate that memory cost.
