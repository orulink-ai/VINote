"""Recorded-audio request planning; service budgets are not model limits.

Boundaries are PCM sample offsets. Every sample belongs to exactly one request;
quiet boundaries are preferred, without inventing word timestamps or trimming
silence out of the recording. Only one small analysis window is held in memory.
"""
from array import array
from dataclasses import dataclass
import math
import sys
import wave


@dataclass(frozen=True)
class RecordedAudioPolicy:
    max_session_audio_bytes: int

    @classmethod
    def from_capabilities(cls, capabilities):
        policy = capabilities.get("recordedAudio") if isinstance(capabilities, dict) else None
        if not isinstance(policy, dict) or type(policy.get("protocol")) is not int or policy.get("protocol") != 1:
            raise ValueError("当前服务尚未提供录音处理规则，请更新服务后重试；所选模型已保留")
        if policy.get("supported") is not True:
            raise ValueError("当前服务的录音处理配置不可用，请检查服务配置；所选模型已保留")
        budget = policy.get("maxSessionAudioBytes")
        if (policy.get("strategy") != "adaptive_pause" or policy.get("policySource") != "service_budget"
                or type(budget) is not int or not 640 <= budget <= 64 * 1024 * 1024
                or budget % 2):
            raise ValueError("录音处理规则无效，尚未提交音频")
        return cls(budget)


def plan_intervals(wav_path, policy, *, start_frame=0):
    """Prefer the latest sustained relative quiet within the budget's last third.

    The 20ms analysis hop and 240ms pause qualification describe acoustics, not
    recognition session durations. For continuous speech choose the quietest
    window in that search region; no model-name-based duration is used.
    """
    with wave.open(str(wav_path), "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (16000, 1, 2):
            raise ValueError("分段规划需要标准单声道录音")
        total = source.getnframes()
        if type(start_frame) is not int or not 0 <= start_frame <= total:
            raise ValueError("已保存的录音处理位置无效")
        maximum = policy.max_session_audio_bytes // 2
        hop = 320
        pause_frames = 3840
        result = []
        start = start_frame
        while start < total:
            cap = min(total, start + maximum)
            if cap == total:
                result.append((start, total))
                break
            search = start + maximum * 2 // 3
            source.setpos(start)
            position, peak, run_start, best_pause = start, 0.0, None, None
            quietest, quietest_at = math.inf, cap
            while position < cap:
                raw = source.readframes(min(hop, cap - position))
                if not raw:
                    raise ValueError("录音数据提前结束，尚未提交音频")
                samples = array("h", raw)
                if sys.byteorder != "little":
                    samples.byteswap()
                energy = sum(sample * sample for sample in samples) / len(samples)
                peak = max(peak, energy)
                end = position + len(samples)
                # Relative amplitude plus a conservative digital-silence floor.
                quiet = energy <= max(64.0, peak * 0.001)
                if position >= search:
                    if energy <= quietest:
                        quietest, quietest_at = energy, position + len(samples) // 2
                    run_start = (position if run_start is None else run_start) if quiet else None
                    if run_start is not None and end - run_start >= pause_frames:
                        best_pause = (run_start + end) // 2
                position = end
            cut = best_pause if best_pause is not None else quietest_at
            cut = max(start + 1, min(cap, cut))
            result.append((start, cut))
            start = cut
        return result
