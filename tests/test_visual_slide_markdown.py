"""TDD tests for code-fence-aware, idempotent visual_slide_markdown injector."""
import uuid
import pytest

from app.services import feishu_native_images
from app.services.visual_slide_markdown import (
    SlideInsertion,
    insert_visual_slides,
    strip_visual_slides,
)

TASK_ID = str(uuid.uuid4())
OTHER_TASK_ID = str(uuid.uuid4())


def test_inserts_under_matched_h2_heading_as_standalone_paragraph():
    md = (
        "# 架构评审会议\n\n"
        "会议概述段落。\n\n"
        "## 系统架构\n\n"
        "核心链路采用离线渲染。\n\n"
        "## 后续行动\n\n"
        "- 完成集成测试\n"
    )
    slides = [
        SlideInsertion(
            filename="slide-01.png",
            caption="系统架构总览",
            target_heading="系统架构",
        ),
        SlideInsertion(
            filename="slide-02.png",
            caption="行动计划与分工",
            target_heading="## 后续行动",
        ),
    ]
    out = insert_visual_slides(md, TASK_ID, slides)
    expected_1 = f"## 系统架构\n\n![系统架构总览](/api/task/{TASK_ID}/artifacts/visuals/slide-01.png)\n\n核心链路采用离线渲染。"
    expected_2 = f"## 后续行动\n\n![行动计划与分工](/api/task/{TASK_ID}/artifacts/visuals/slide-02.png)\n\n- 完成集成测试"
    assert expected_1 in out
    assert expected_2 in out
    assert "\n\n\n" not in out


def test_strict_idempotency_and_clean_replacement_on_rerun():
    md = "# 会议纪要\n\n## 核心结论\n\n正文内容。\n\n## 风险与对策\n\n风险说明。\n"
    slides_v1 = [
        SlideInsertion("slide-01.png", "核心结论图", "核心结论"),
        SlideInsertion("slide-02.png", "风险矩阵", "风险与对策"),
    ]
    once = insert_visual_slides(md, TASK_ID, slides_v1)
    twice = insert_visual_slides(once, TASK_ID, slides_v1)
    assert twice == once

    slides_v2 = [SlideInsertion("slide-01.png", "新版核心结论", "核心结论")]
    replaced = insert_visual_slides(once, TASK_ID, slides_v2)
    assert "slide-02.png" not in replaced
    assert replaced.count("slide-01.png") == 1
    assert "![新版核心结论]" in replaced
    assert insert_visual_slides(replaced, TASK_ID, slides_v2) == replaced


def test_ignores_headings_and_image_refs_inside_backtick_and_tilde_code_fences():
    md = (
        "# 研发复盘\n\n"
        "```markdown\n"
        "## 系统架构\n"
        f"![代码示例](/api/task/{TASK_ID}/artifacts/visuals/slide-99.png)\n"
        "```\n\n"
        "~~~md\n"
        "## 系统架构\n"
        "~~~\n\n"
        "## 系统架构\n\n"
        "真正的架构章节正文。\n"
    )
    slides = [SlideInsertion("slide-01.png", "真实架构图", "系统架构")]
    out = insert_visual_slides(md, TASK_ID, slides)
    # Code fence contents remain completely untouched
    assert f"```markdown\n## 系统架构\n![代码示例](/api/task/{TASK_ID}/artifacts/visuals/slide-99.png)\n```" in out
    assert "~~~md\n## 系统架构\n~~~" in out
    # Inserted only under the real heading outside fences
    assert f"## 系统架构\n\n![真实架构图](/api/task/{TASK_ID}/artifacts/visuals/slide-01.png)\n\n真正的架构章节正文。" in out
    assert insert_visual_slides(out, TASK_ID, slides) == out


def test_fallback_placement_when_target_heading_missing_or_no_h2():
    md_with_h2 = "# 周会\n\n引言。\n\n## 项目进度\n\n一切顺利。\n"
    out = insert_visual_slides(
        md_with_h2,
        TASK_ID,
        [SlideInsertion("slide-01.png", "总览图", "不存在的章节")],
    )
    assert f"## 项目进度\n\n![总览图](/api/task/{TASK_ID}/artifacts/visuals/slide-01.png)\n\n一切顺利。" in out

    md_h1_only = "# 简短周会\n\n这是一段正文。\n"
    out_h1 = insert_visual_slides(
        md_h1_only,
        TASK_ID,
        [SlideInsertion("slide-01.png", "简报图", "任何章节")],
    )
    assert f"# 简短周会\n\n![简报图](/api/task/{TASK_ID}/artifacts/visuals/slide-01.png)\n\n这是一段正文。" in out_h1
    assert insert_visual_slides(out_h1, TASK_ID, [SlideInsertion("slide-01.png", "简报图", "任何章节")]) == out_h1

    md_plain = "纯文本会议纪要，没有标题。\n"
    out_plain = insert_visual_slides(
        md_plain,
        TASK_ID,
        [SlideInsertion("slide-01.png", "纯文本图", "任何章节")],
    )
    assert out_plain.startswith(f"![纯文本图](/api/task/{TASK_ID}/artifacts/visuals/slide-01.png)\n\n纯文本会议纪要")
    assert insert_visual_slides(out_plain, TASK_ID, [SlideInsertion("slide-01.png", "纯文本图", "任何章节")]) == out_plain


def test_empty_slide_list_leaves_clean_markdown_byte_identical_and_preserves_screenshots():
    md = (
        "# 纪要\n\n"
        f"![关键截图](/api/task/{TASK_ID}/artifacts/screenshots/frame_01.png)\n\n"
        f"![其他任务](/api/task/{OTHER_TASK_ID}/artifacts/visuals/slide-01.png)\n\n"
        "## 正文\n\n"
        "保留原始空白   \n"
    )
    assert insert_visual_slides(md, TASK_ID, []) == md
    assert strip_visual_slides(md, TASK_ID) == md

    with_slide = insert_visual_slides(md, TASK_ID, [SlideInsertion("slide-01.png", "图一", "正文")])
    assert f"/api/task/{TASK_ID}/artifacts/screenshots/frame_01.png" in with_slide
    assert f"/api/task/{OTHER_TASK_ID}/artifacts/visuals/slide-01.png" in with_slide
    stripped = strip_visual_slides(with_slide, TASK_ID)
    assert stripped == md


def test_sanitizes_caption_for_feishu_compatibility():
    md = "# 标题\n\n## 指标\n\n数据说明。\n"
    dirty_caption = "第一行[含括号]\n第二行\t含制表符\x00" + ("字" * 200)
    out = insert_visual_slides(md, TASK_ID, [SlideInsertion("slide-01.png", dirty_caption, "指标")])
    image_line = [line for line in out.splitlines() if f"/api/task/{TASK_ID}/artifacts/visuals/slide-01.png" in line]
    assert len(image_line) == 1
    match = feishu_native_images._IMAGE.fullmatch(image_line[0])
    assert match is not None
    assert "[" not in match.group(1) and "]" not in match.group(1)
    assert "\n" not in match.group(1) and "\x00" not in match.group(1)
    assert len(match.group(1)) <= 120


def test_rejects_invalid_task_id_or_filename():
    with pytest.raises(ValueError):
        insert_visual_slides("# Hi", "not-a-uuid", [SlideInsertion("slide-01.png", "ok", "Hi")])
    with pytest.raises(ValueError):
        insert_visual_slides("# Hi", TASK_ID, [SlideInsertion("../evil.png", "ok", "Hi")])
    with pytest.raises(ValueError):
        insert_visual_slides("# Hi", TASK_ID, [SlideInsertion("slide-01.html", "ok", "Hi")])
