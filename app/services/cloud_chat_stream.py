"""Collect an OpenAI SSE completion without losing proxy keep-alive traffic."""
import json
import time

from app.services.summary_failure import SummaryResultUnconfirmed, sse_terminal_context


def collect_chat_stream(response, *, started: float, max_seconds: float = 900) -> dict:
    parts = []
    usage = {}
    model = None
    finish_reason = None
    finish_observed = False
    size = 0
    event_lines = []

    def events():
        for line in response.iter_lines():
            if time.monotonic() - started > max_seconds:
                raise SummaryResultUnconfirmed('timeout', status_code=504)
            if not line:
                if event_lines:
                    yield "\n".join(event_lines)
                    event_lines.clear()
            elif line.startswith("data:"):
                event_lines.append(line[5:].lstrip())
        if event_lines:
            yield "\n".join(event_lines)

    completed = False
    for event in events():
        if event == "[DONE]":
            completed = True
            break
        try:
            data = json.loads(event)
        except ValueError:
            raise SummaryResultUnconfirmed() from None
        if not isinstance(data, dict) or data.get("error"):
            raise SummaryResultUnconfirmed()
        model = data.get("model") or model
        if isinstance(data.get("usage"), dict):
            usage = data["usage"]
        choices = data.get("choices") or []
        if not isinstance(choices, list):
            raise SummaryResultUnconfirmed()
        for choice in choices:
            if not isinstance(choice, dict):
                raise SummaryResultUnconfirmed()
            if choice.get("index", 0) != 0:
                continue
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                raise SummaryResultUnconfirmed()
            content = delta.get("content")
            # Reasoning keeps the connection active but is not the final answer.
            if isinstance(content, str):
                size += len(content)
                if size > 8_000_000:
                    raise SummaryResultUnconfirmed()
                parts.append(content)
            finish_observed = finish_observed or choice.get("finish_reason") is not None
            finish_reason = choice.get("finish_reason") or finish_reason
    if not completed or finish_reason != "stop":
        raise SummaryResultUnconfirmed(terminal_diagnostic=sse_terminal_context(
            done_seen=completed, finish_reason=finish_reason, finish_observed=finish_observed))
    return {"model": model, "usage": usage,
            "choices": [{"message": {"content": "".join(parts)}, "finish_reason": finish_reason}]}
