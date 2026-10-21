"""Task-owned presentation metadata and authentic, source-bound screenshots."""
import re
import shutil
from uuid import UUID


def render_presentation(artifacts, context, markdown):
    # Model output never chooses external image URLs or executable HTML assets.
    markdown = re.sub(r'!\[[^\]\n]*\]\([^\n]*?\)', '', markdown)
    markdown = re.sub(r'\[\[Screenshot:[^\]]*\]\]', '', markdown)
    if context.presentation in {'comic', 'infographic'}:
        from app.services.summary_visual_generation import render_review_visual
        return render_review_visual(artifacts, context, markdown)
    if context.presentation != 'illustrated':
        return markdown
    evidence = context.video_evidence
    if evidence is None or not evidence.frames:
        raise ValueError('缺少可核验的真实截图，图文不可用')
    folder = context.task_dir / 'screenshots'
    if folder.is_symlink():
        raise ValueError('截图目录不可用')
    folder.mkdir(exist_ok=True)
    figures = getattr(context, 'presentation_figures', None)
    references = re.findall(r'\[FRAME:\d{4,}\]', markdown)
    if (not isinstance(figures, list) or not 0 < len(figures) <= 8
            or sorted(references) != sorted(figure['frame_ref'] for figure in figures)):
        raise ValueError('图文尚未完成：模型没有返回可核验的段落选帧，未使用默认截图')
    from app.services.video_evidence_service import _frame_digest
    for index, figure in enumerate(figures):
        frame_index = int(figure['frame_ref'][7:-1]) - 1
        if not 0 <= frame_index < len(evidence.frames):
            raise ValueError('图文尚未完成：选帧超出真实材料')
        frame = evidence.frames[frame_index]
        expected = getattr(evidence, '_summary_frame_hashes', {}).get(frame.image_path)
        if not expected or _frame_digest(frame.image_path) != expected:
            raise ValueError('图文尚未完成：原截图已变化')
        passage = figure['after_passage']
        if markdown.count(passage + '\n\n' + figure['frame_ref']) != 1:
            raise ValueError('图文尚未完成：选帧与复核段落不匹配')
        destination = folder / f'summary-source-{index}.jpg'
        if destination.is_symlink():
            raise ValueError('截图路径不可用')
        shutil.copyfile(frame.image_path, destination)
        if _frame_digest(destination) != expected:
            raise ValueError('图文尚未完成：截图复制核验失败')
        from app.llm.meeting_markdown import figure_markdown
        image = figure_markdown(figure['caption'], frame.timestamp,
            f'/api/task/{context.task_id}/artifacts/screenshots/{destination.name}')
        markdown = markdown.replace(figure['frame_ref'], image, 1)
    return markdown


def read_presentation(artifacts, owner, task):
    """Read metadata for an authorized task; never infer it from the title/body."""
    import json
    try:
        if str(UUID(task)) != task:
            return None
        folder = artifacts.find_task_dir(task)
        if folder is None or folder.is_symlink() or folder.resolve().parent != artifacts.output_dir.resolve():
            return None
        marker = folder / 'recording_owner'
        path = folder / 'summary_presentation.json'
        if marker.is_symlink() or marker.read_text(encoding='utf-8') != owner or path.is_symlink():
            return None
        if path.stat().st_size > 16384:
            return None
        payload = json.loads(path.read_text(encoding='utf-8'))
        if payload.get('task_id') != task or payload.get('protocol') != 1:
            return None
        return payload
    except (OSError, ValueError, TypeError):
        return None
