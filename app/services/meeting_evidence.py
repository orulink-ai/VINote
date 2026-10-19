"""Select original ASR windows, never estimated diarization sentence positions."""
import math


def original_asr_evidence(value: dict) -> dict:
    """Unwrap bounded historical speaker wrappers without changing source text."""
    seen = set()
    original_text = None
    current = value
    for _ in range(8):
        if not isinstance(current, dict) or id(current) in seen:
            raise ValueError('转写证据结构无法核验')
        seen.add(id(current))
        text, segments = current.get('full_text'), current.get('segments')
        if not isinstance(text, str) or not isinstance(segments, list):
            raise ValueError('原始转写证据不完整')
        normalized = ''.join(text.split())
        if original_text is not None and normalized != original_text:
            raise ValueError('转写证据正文不一致，未混用时间轴')
        original_text = normalized
        metadata = current.get('metadata') or {}
        if not isinstance(metadata, dict):
            raise ValueError('转写证据属性无法核验')
        nested = metadata.get('asr_evidence')
        if nested is None:
            if len(segments) > 100000:
                raise ValueError('转写证据超出处理预算')
            for segment in segments:
                if (not isinstance(segment, dict) or not isinstance(segment.get('text'), str)
                        or type(segment.get('start')) not in (float, int)
                        or type(segment.get('end')) not in (float, int)
                        or not math.isfinite(segment['start']) or not math.isfinite(segment['end'])
                        or not 0 <= segment['start'] < segment['end']):
                    raise ValueError('原始转写时间区间无法核验')
            return current
        current = nested
    raise ValueError('转写证据嵌套过深，未使用估算时间代替')
