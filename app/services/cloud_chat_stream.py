"""Collect an OpenAI SSE completion without losing proxy keep-alive traffic."""
import json
import time

from fastapi import HTTPException


def collect_chat_stream(response, *, started: float, max_seconds: float = 900) -> dict:
    parts = []
    usage = {}
    model = None
    finish_reason = None
    size = 0
    event_lines = []

    def events():
        for line in response.iter_lines():
            if time.monotonic() - started > max_seconds:
                raise HTTPException(504, "云端模型生成超过时间上限，请稍后重试")
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
            raise HTTPException(502, "云端模型返回无效的流式数据") from None
        if not isinstance(data, dict) or data.get("error"):
            raise HTTPException(502, "云端模型流式处理失败，请检查服务状态")
        model = data.get("model") or model
        if isinstance(data.get("usage"), dict):
            usage = data["usage"]
        choices = data.get("choices") or []
        if not isinstance(choices, list):
            raise HTTPException(502, "云端模型返回无效的流式候选结果")
        for choice in choices:
            if not isinstance(choice, dict):
                raise HTTPException(502, "云端模型返回无效的流式候选结果")
            if choice.get("index", 0) != 0:
                continue
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                raise HTTPException(502, "云端模型返回无效的流式内容")
            content = delta.get("content")
            # Reasoning keeps the connection active but is not the final answer.
            if isinstance(content, str):
                size += len(content)
                if size > 8_000_000:
                    raise HTTPException(502, "云端模型输出过长")
                parts.append(content)
            finish_reason = choice.get("finish_reason") or finish_reason
    if not completed or finish_reason != "stop":
        raise HTTPException(502, "云端模型输出未完整结束，请重试；不会保存截断的纪要")
    return {"model": model, "usage": usage,
            "choices": [{"message": {"content": "".join(parts)}, "finish_reason": finish_reason}]}
