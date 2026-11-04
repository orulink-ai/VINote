"""Collect an OpenAI SSE completion without losing proxy keep-alive traffic."""
import json
import logging
import time
import httpx

from app.services.summary_failure import SummaryResultUnconfirmed, sse_terminal_context


def collect_chat_stream(response, *, started: float, max_seconds: float = 900) -> dict:
    parts = []
    usage = {}
    model = None
    finish_reason = None
    finish_observed = False
    size = 0
    delta_count = 0
    request_id = None
    http_request_id = getattr(response, "headers", {}).get("x-request-id")
    completed = False
    event_lines = []
    first_line = last_line = None
    line_count = event_count = 0

    def failed(error):
        from app.services.summary_failure import safe_summary_failure_context, safe_stream_progress
        context = error.summary_failure_context
        if context is not None:
            context['http_request_id'] = http_request_id
            finish = (finish_reason if finish_reason in ('stop', 'length', 'content_filter', 'tool_calls', 'function_call')
                      else 'missing' if not finish_observed else 'other')
            now = time.monotonic()
            context['stream'] = safe_stream_progress(dict(content_chars=size, content_deltas=delta_count,
                elapsed_seconds=max(0, int(now - started)), finish=finish,
                done_seen=completed, request_id=request_id, line_count=line_count, event_count=event_count,
                first_line_ms=None if first_line is None else max(0, int((first_line - started) * 1000)),
                last_line_ms=None if last_line is None else max(0, int((last_line - started) * 1000)),
                idle_gap_ms=None if last_line is None else max(0, int((now - last_line) * 1000))))
            error.summary_failure_context = safe_summary_failure_context(context)
        return error

    def events():
        try:
            lines = response.iter_lines()
            yield from read_lines(lines)
        except httpx.RequestError as error:
            logging.getLogger(__name__).warning("Cloud chat transport failed: kind=%s", type(error).__name__)
            raise failed(SummaryResultUnconfirmed('timeout' if isinstance(error, httpx.TimeoutException) else 'connection')) from None

    def invalid(category):
        return failed(SummaryResultUnconfirmed(terminal_diagnostic={
            'diagnostic_protocol': 'sse_stream/1', 'category': category}))

    def read_lines(lines):
        nonlocal first_line, last_line, line_count, event_count
        for line in lines:
            now = time.monotonic()
            if first_line is None:
                first_line = now
            last_line = now
            line_count += 1
            if now - started > max_seconds:
                raise failed(SummaryResultUnconfirmed('timeout', status_code=504))
            if not line:
                if event_lines:
                    event_count += 1
                    yield "\n".join(event_lines)
                    event_lines.clear()
            elif line.startswith("data:"):
                event_lines.append(line[5:].lstrip())
        if event_lines:
            event_count += 1
            yield "\n".join(event_lines)

    for event in events():
        if event == "[DONE]":
            completed = True
            break
        try:
            data = json.loads(event)
        except ValueError:
            raise invalid('invalid_event') from None
        if not isinstance(data, dict):
            raise invalid('invalid_event')
        if data.get("error"):
            raise invalid('provider_error')
        candidate = data.get("id")
        if request_id is None and isinstance(candidate, str):
            from app.services.summary_failure import safe_stream_progress
            check = safe_stream_progress(dict(content_chars=0, content_deltas=0, elapsed_seconds=0,
                                               finish='missing', done_seen=False, request_id=candidate))
            request_id = check['request_id']
        model = data.get("model") or model
        if isinstance(data.get("usage"), dict):
            usage = data["usage"]
        choices = data.get("choices") or []
        if not isinstance(choices, list):
            raise invalid('invalid_choices')
        for choice in choices:
            if not isinstance(choice, dict):
                raise invalid('invalid_choices')
            if choice.get("index", 0) != 0:
                continue
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                raise invalid('invalid_delta')
            content = delta.get("content")
            # Reasoning keeps the connection active but is not the final answer.
            if isinstance(content, str):
                size += len(content)
                if content:
                    delta_count += 1
                if size > 8_000_000:
                    raise invalid('content_limit')
                parts.append(content)
            finish_observed = finish_observed or choice.get("finish_reason") is not None
            finish_reason = choice.get("finish_reason") or finish_reason
    if not completed or finish_reason != "stop":
        raise failed(SummaryResultUnconfirmed(terminal_diagnostic=sse_terminal_context(
            done_seen=completed, finish_reason=finish_reason, finish_observed=finish_observed)))
    return {"model": model, "usage": usage,
            "choices": [{"message": {"content": "".join(parts)}, "finish_reason": finish_reason}]}
