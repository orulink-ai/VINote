"""Content-free failure classification for task recovery, never provider text."""
from app.services.summary_failure import (
    SummaryResultUnconfirmed, SUMMARY_UNCONFIRMED_CODE, SUMMARY_UNCONFIRMED_COPY,
    safe_summary_failure_context,
)
from app.services.asr_stream_service import (
    ASRServiceError,
    _TRANSIENT_CODES,
    _KNOWN_CODES,
    safe_session_id,
    safe_transport_diagnostic,
)

UNKNOWN_MESSAGE = "转写服务未能确认最终识别结果，请检查原任务后重试当前模型"
UNKNOWN_COPY = "转写结果尚未确认，原文件已保留。请查看原任务结果，不要重复提交。"
EMPTY_RESULT_COPY = "转写服务返回空结果，尚未确认该区间的完整识别结果。原文件已保留，请查看原任务，不要重复提交。"

def safe_asr_failure_context(value):
    """Private artifact projection, never arbitrary exception metadata."""
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        return None

    def diagnostic(raw):
        if not isinstance(raw, dict):
            return {}
        result = {}
        code = raw.get("code")
        if isinstance(code, str) and code in _KNOWN_CODES:
            result["code"] = code
        session_id = safe_session_id(raw.get("session_id"))
        if session_id:
            result["session_id"] = session_id
        if raw.get("stage") in ("asr", "session", "audio"):
            result["stage"] = raw["stage"]
        if type(raw.get("sent_all")) is bool:
            result["sent_all"] = raw["sent_all"]
        # Never copy the raw transport/exception dict, even for numeric-looking fields.
        result.update(safe_transport_diagnostic(raw))
        return result

    attempts = []
    raw_attempts = value.get("asr_attempts")
    reasons = {"non_retryable", "network", "http_429", "http_502", "http_503", "http_504"} | _TRANSIENT_CODES
    if isinstance(raw_attempts, list):
        for raw in raw_attempts[:3]:
            if not isinstance(raw, dict) or type(raw.get("attempt")) is not int or not 1 <= raw["attempt"] <= 3:
                continue
            item = {"attempt": raw["attempt"]}
            if raw.get("status") in ("failed", "success", "no_speech"):
                item["status"] = raw["status"]
            reason = raw.get("reason")
            if isinstance(reason, str) and reason in reasons:
                item["reason"] = reason
            details = diagnostic(raw.get("diagnostic"))
            if details:
                item["diagnostic"] = details
            attempts.append(item)
    details = diagnostic(value.get("diagnostic"))
    if not details and not attempts:
        return None
    return {"schema_version": 1, "diagnostic": details, "asr_attempts": attempts}


def failure_details(error):
    if isinstance(error, SummaryResultUnconfirmed):
        result = {'error_code': SUMMARY_UNCONFIRMED_CODE, 'retryable': False}
        context = safe_summary_failure_context(getattr(error, 'summary_failure_context', None))
        if context is not None:
            result['summary_failure_context'] = context
        return result
    if isinstance(error, ASRServiceError):
        code = error.code
        if error.sent_all and code in _TRANSIENT_CODES:
            code = "unknown_result"
        result = {"error_code": code, "retryable": bool(error.retry_reason) and code != "unknown_result"}
        metadata = getattr(error, "asr_metadata", None)
        # Do not invent attempt/session/provider codes for old bare errors.
        if isinstance(metadata, dict) or error.session_id or error._transport_diagnostic:
            context = safe_asr_failure_context({
                "schema_version": 1, "diagnostic": error.diagnostic,
                "asr_attempts": metadata.get("asr_attempts") if isinstance(metadata, dict) else None,
            })
            if context:
                result["asr_failure_context"] = context
        return result
    transport = safe_transport_diagnostic(getattr(error, "asr_transport_diagnostic", None))
    if transport:
        return {"asr_failure_context": safe_asr_failure_context({
            "schema_version": 1, "diagnostic": transport})}
    return {}


def recovery_status(status):
    result = dict(status)
    code = result.get("error_code")
    context = safe_summary_failure_context(result.pop('summary_failure_context', None))
    if code == SUMMARY_UNCONFIRMED_CODE:
        if context is not None and result.get('status') in {'failed', 'error'}:
            result['summary_failure_context'] = context
        result.update(retryable=False, message=SUMMARY_UNCONFIRMED_COPY)
        return result
    if code not in _KNOWN_CODES:
        code = None
    # Older artifacts discarded the typed failure. This exact generic ASR copy
    # cannot establish a safe retry; do not infer success, silence or transience.
    if result.get("status") in {"failed", "error"} and not code and result.get("message") == UNKNOWN_MESSAGE:
        code = "unknown_result"
    if code:
        result["error_code"] = code
        if code not in _TRANSIENT_CODES:
            result["retryable"] = False
        if code in {"unknown_result", "unknown_error", "asr_incomplete_result"}:
            result["message"] = UNKNOWN_COPY
        elif code in {"asr_empty_result", "empty_result_unverified"}:
            result["message"] = EMPTY_RESULT_COPY
    return result
