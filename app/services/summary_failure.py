"""Typed ambiguous summary outcomes; no provider text or replay authorization."""
from fastapi import HTTPException
import re

SUMMARY_UNCONFIRMED_CODE = 'summary_result_unconfirmed'
SUMMARY_OUTPUT_INVALID_CODE = 'summary_output_invalid'
SUMMARY_OUTPUT_INVALID_COPY = (
    '模型返回格式不完整，本次未保存为完成稿。原逐字稿、已有纪要与原文件已保留，未自动重试。'
)
SUMMARY_UNCONFIRMED_COPY = (
    '总结结果尚未确认，完整材料已保留，未自动重试。请查询原任务；'
    '如需再次总结，请明确确认新的独立总结操作。'
)

_TERMINAL_FINISHES = ('stop', 'length', 'content_filter', 'tool_calls',
                      'function_call', 'missing', 'other')


def safe_http_request_id(value):
    if isinstance(value, str) and re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', value):
        return value.lower()
    return None


def safe_stream_progress(value):
    if not isinstance(value, dict):
        return None
    chars, deltas, elapsed = (value.get(k) for k in ('content_chars', 'content_deltas', 'elapsed_seconds'))
    finish, done, request_id = (value.get(k) for k in ('finish', 'done_seen', 'request_id'))
    if (any(type(n) is not int or not 0 <= n <= 100000000 for n in (chars, deltas, elapsed))
            or type(done) is not bool or finish not in _TERMINAL_FINISHES):
        return None
    if not (isinstance(request_id, str) and re.fullmatch(r'chatcmpl-[a-f0-9]{16,64}', request_id)):
        request_id = None
    result = dict(content_chars=chars, content_deltas=deltas, elapsed_seconds=elapsed,
                  finish=finish, done_seen=done, request_id=request_id)
    # Optional fields preserve compatibility with historical diagnostics. Never
    # copy unrecognized values from provider or task data into persisted state.
    for key in ('line_count', 'event_count'):
        item = value.get(key)
        if type(item) is int and 0 <= item <= 100000000:
            result[key] = item
    for key in ('first_line_ms', 'last_line_ms', 'idle_gap_ms'):
        if key in value:
            item = value[key]
            if item is None or type(item) is int and 0 <= item <= 100000000:
                result[key] = item
    return result


def _with_stream(result, value):
    http_request_id = safe_http_request_id(value.get('http_request_id'))
    if http_request_id is not None:
        result['http_request_id'] = http_request_id
    progress = safe_stream_progress(value.get('stream'))
    if progress is not None:
        result['stream'] = progress
    return result


def safe_summary_failure_context(value):
    """Detached private projection; never retain arbitrary provider metadata."""
    if not isinstance(value, dict):
        return None
    if value.get('diagnostic_protocol') == 'summary_format/1':
        category = value.get('category')
        if type(category) is not str or category not in ('syntax', 'duplicate_key', 'invalid_constant', 'invalid_json'):
            return None
        result = {'diagnostic_protocol': 'summary_format/1', 'category': category}
        if value.get('output_stage') in ('draft', 'review'):
            result['output_stage'] = value['output_stage']
        for key in ('line', 'column', 'offset'):
            number = value.get(key)
            if type(number) is int and (0 if key == 'offset' else 1) <= number <= 100000000:
                result[key] = number
        return result
    if value.get('diagnostic_protocol') == 'summary_transport/1':
        category = value.get('category')
        if type(category) is str and category in ('http524', 'timeout', 'connection'):
            return _with_stream({'diagnostic_protocol': 'summary_transport/1', 'category': category}, value)
        return None
    if value.get('diagnostic_protocol') == 'sse_stream/1':
        category = value.get('category')
        if type(category) is str and category in ('invalid_event', 'provider_error', 'invalid_choices', 'invalid_delta', 'content_limit'):
            return _with_stream({'diagnostic_protocol': 'sse_stream/1', 'category': category}, value)
        return None
    if value.get('diagnostic_protocol') != 'sse_terminal/1':
        return None
    done = value.get('done_seen')
    finish = value.get('finish')
    if type(done) is not bool or type(finish) is not str or finish not in _TERMINAL_FINISHES:
        return None
    if done and finish == 'stop':
        return None
    category = ('non_stop_finish' if done else 'missing_done' if finish == 'stop'
                else 'missing_done_and_non_stop_finish')
    if value.get('category') != category:
        return None
    return _with_stream({'diagnostic_protocol': 'sse_terminal/1', 'done_seen': done,
            'finish': finish, 'category': category}, value)


def sse_terminal_context(*, done_seen, finish_reason, finish_observed):
    """Normalize only terminal observations, without interpreting unknown values."""
    finish = (finish_reason if type(finish_reason) is str and finish_reason in _TERMINAL_FINISHES[:5]
              else 'missing' if finish_reason is None and not finish_observed else 'other')
    return safe_summary_failure_context({
        'diagnostic_protocol': 'sse_terminal/1', 'done_seen': done_seen, 'finish': finish,
        'category': ('non_stop_finish' if done_seen else 'missing_done' if finish == 'stop'
                     else 'missing_done_and_non_stop_finish'),
    })


class SummaryResultUnconfirmed(HTTPException):
    def __init__(self, reason='incomplete', *, status_code=502, terminal_diagnostic=None):
        self.summary_failure_context = safe_summary_failure_context(terminal_diagnostic)
        if self.summary_failure_context is None and reason in ('http524', 'timeout', 'connection'):
            self.summary_failure_context = {'diagnostic_protocol': 'summary_transport/1', 'category': reason}
        prefix = {
            'timeout': '云端模型响应超时。',
            'connection': '云端模型响应连接中断。',
            'http524': '云端模型请求返回 HTTP 524。',
        }.get(reason, '')
        super().__init__(status_code=status_code, detail=prefix + SUMMARY_UNCONFIRMED_COPY)
