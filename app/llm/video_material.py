"""Bind video materials for one summary, outside text-only tracing decorators."""
from contextlib import contextmanager
from contextvars import ContextVar

_material = ContextVar('summary_video_material', default=None)


def has_video_material() -> bool:
    return _material.get() is not None


def video_reference_ids():
    from app.llm.source_references import frame_reference
    binding = _material.get()
    return [frame_reference(index) for index in range(len(binding[0].frames))] if binding else []


def visual_source_bindings():
    """Input provenance only; a model's visual interpretation is not proof."""
    from app.llm.source_references import frame_reference
    from app.services.video_evidence_service import supports_images
    binding = _material.get()
    if binding is None:
        return {}
    evidence, capabilities = binding
    return {frame_reference(index): {'image': supports_images(capabilities),
            'ocr': frame.ocr_text if frame.ocr_status == 'recognized' else None}
            for index, frame in enumerate(evidence.frames)}


@contextmanager
def bind_video_material(evidence, capabilities):
    if evidence is not None:
        evidence.validate_input(capabilities)
    token = _material.set((evidence, capabilities) if evidence is not None else None)
    try:
        yield
    finally:
        _material.reset(token)


def video_user_content(prompt: str) -> str | list[dict]:
    binding = _material.get()
    if binding is None:
        return prompt
    evidence, capabilities = binding
    return evidence.user_content(prompt, capabilities=capabilities)


def anthropic_user_content(prompt: str) -> list[dict]:
    content = video_user_content(prompt)
    if isinstance(content, str):
        return [{'type': 'text', 'text': content}]
    result = []
    for block in content:
        if block['type'] == 'text':
            result.append(block)
        else:
            encoded = block['image_url']['url'].split(',', 1)[1]
            result.append({'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg',
                                                     'data': encoded}})
    return result
