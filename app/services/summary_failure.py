"""Typed ambiguous summary outcomes; no provider text or replay authorization."""
from fastapi import HTTPException

SUMMARY_UNCONFIRMED_CODE = 'summary_result_unconfirmed'
SUMMARY_UNCONFIRMED_COPY = (
    '总结结果尚未确认，完整材料已保留，未自动重试。请查询原任务；'
    '如需再次总结，请明确确认新的独立总结操作。'
)


class SummaryResultUnconfirmed(HTTPException):
    def __init__(self, reason='incomplete', *, status_code=502):
        prefix = {
            'timeout': '云端模型响应超时。',
            'connection': '云端模型响应连接中断。',
            'http524': '云端模型请求返回 HTTP 524。',
        }.get(reason, '')
        super().__init__(status_code=status_code, detail=prefix + SUMMARY_UNCONFIRMED_COPY)
