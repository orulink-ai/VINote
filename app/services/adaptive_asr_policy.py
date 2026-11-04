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
    max_session_audio_bytes: int | None = None
    strategy: str = "adaptive_pause"

    @classmethod
    def from_capabilities(cls, capabilities):
        policy = capabilities.get("recordedAudio") if isinstance(capabilities, dict) else None
        if not isinstance(policy, dict) or type(policy.get("protocol")) is not int or policy.get("protocol") != 1:
            raise ValueError("当前服务尚未提供录音处理规则，请更新服务后重试；所选模型已保留")
        if policy.get("supported") is not True:
            raise ValueError("当前服务的录音处理配置不可用，请检查服务配置；所选模型已保留")
        if policy.get("strategy") == "single_request" and policy.get("policySource") == "provider_model":
            return cls(None, "single_request")
        budget = policy.get("maxSessionAudioBytes")
        if (policy.get("strategy") != "adaptive_pause" or policy.get("policySource") != "service_budget"
                or type(budget) is not int or not 640 <= budget <= 64 * 1024 * 1024
                or budget % 2):
            raise ValueError("录音处理规则无效，尚未提交音频")
        return cls(budget, "adaptive_pause")


@dataclass(frozen=True)
class RecordingModelPolicy(RecordedAudioPolicy):
    """Complete recording contract declared by a model's public capabilities."""

    use_cases: frozenset[str] = frozenset()
    audio_delivery: str | None = None
    audio_formats: tuple[str, ...] = ()
    max_audio_seconds: int | None = None
    max_audio_bytes: int | None = None
    speaker_diarization: bool = False
    utterance_timestamps: bool = False
    protocols: tuple[str, ...] = ()

    @property
    def meeting_blocked_reason(self) -> str:
        """Why this model cannot take a whole meeting recording; empty if it can."""
        if "meeting" not in self.use_cases:
            return "当前语音模型未声明会议录音用途，只能用于实时转写"
        if "asr-recording" not in self.protocols:
            return "当前语音模型不支持整段录音提交，只能用于实时转写"
        if self.audio_delivery != "public":
            return "当前服务的音频地址不能被语音服务访问，会议转写暂不可用"
        if "wav" not in self.audio_formats:
            return "当前语音模型不支持 WAV 会议录音"
        if self.strategy != "single_request":
            return "当前语音模型不支持整段识别，只能用于实时转写"
        if not self.speaker_diarization:
            return "当前模型没有说话人分离能力，不能用于会议纪要"
        if not self.utterance_timestamps:
            return "当前模型不返回发言时间戳，不能用于会议转写"
        if not (isinstance(self.max_audio_seconds, int) and self.max_audio_seconds > 0):
            return "当前模型未声明可处理的录音时长"
        if not (isinstance(self.max_audio_bytes, int) and self.max_audio_bytes > 0):
            return "当前模型未声明可处理的录音大小"
        return ""

    @property
    def meeting_ready(self) -> bool:
        return not self.meeting_blocked_reason

    @classmethod
    def from_capabilities(cls, capabilities):
        recorded = RecordedAudioPolicy.from_capabilities(capabilities)
        if not isinstance(capabilities, dict):
            raise ValueError("模型能力格式无效，尚未提交音频")
        use_cases = capabilities.get("useCases")
        protocols = capabilities.get("protocols")
        formats = capabilities.get("audioFormats")
        # The first VILab contract exposed only recordedAudio. Keep those
        # installations on their declared adaptive transport; meeting routing
        # requires the complete, newer declaration below.
        for name, value in (("用途", use_cases), ("协议", protocols), ("格式", formats)):
            if value is not None and (not isinstance(value, list)
                    or not all(isinstance(item, str) for item in value)):
                raise ValueError(f"录音模型{name}声明无效，尚未提交音频")
        delivery = capabilities.get("audioDelivery")
        if delivery is not None and not isinstance(delivery, str):
            raise ValueError("录音传输声明无效，尚未提交音频")
        seconds = capabilities.get("maxAudioSeconds")
        maximum_bytes = capabilities.get("maxAudioBytes")
        for value in (seconds, maximum_bytes):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError("录音时长或大小声明无效，尚未提交音频")
        return cls(
            max_session_audio_bytes=recorded.max_session_audio_bytes,
            strategy=recorded.strategy,
            use_cases=frozenset(use_cases or ()),
            audio_delivery=delivery,
            audio_formats=tuple(formats or ()),
            max_audio_seconds=seconds,
            max_audio_bytes=maximum_bytes,
            speaker_diarization=capabilities.get("speakerDiarization") is True,
            utterance_timestamps=capabilities.get("utteranceTimestamps") is True,
            protocols=tuple(protocols or ()),
        )


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
