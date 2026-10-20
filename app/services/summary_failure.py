"""Typed ambiguous summary outcomes; no provider text or replay authorization."""
from fastapi import HTTPException

SUMMARY_UNCONFIRMED_CODE = 'summary_result_unconfirmed'
SUMMARY_UNCONFIRMED_COPY = (
    '总结结果尚未确认，完整材料已保留，未自动重试。请查询原任务；'
    '如需再次总结，请明确确认新的独立总结操作。'
)

_TERMINAL_FINISHES = ('stop', 'length', 'content_filter', 'tool_calls',
                      'function_call', 'missing', 'other')


def safe_summary_failure_context(value):
    """Detached private projection; never retain arbitrary provider metadata."""
    if not isinstance(value, dict) or value.get('diagnostic_protocol') != 'sse_terminal/1':
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
    return {'diagnostic_protocol': 'sse_terminal/1', 'done_seen': done,
            'finish': finish, 'category': category}


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
        prefix = {
            'timeout': '云端模型响应超时。',
            'connection': '云端模型响应连接中断。',
            'http524': '云端模型请求返回 HTTP 524。',
        }.get(reason, '')
        super().__init__(status_code=status_code, detail=prefix + SUMMARY_UNCONFIRMED_COPY)
