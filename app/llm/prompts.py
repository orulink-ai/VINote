from typing import Literal

OutputLanguage = Literal["en", "zh-CN"]
SummaryMode = Literal["default", "accurate", "oneshot"]

DEFAULT_OUTPUT_LANGUAGE: OutputLanguage = "zh-CN"
DEFAULT_SUMMARY_MODE: SummaryMode = "default"
SUPPORTED_OUTPUT_LANGUAGES: tuple[OutputLanguage, ...] = ("en", "zh-CN")
SUPPORTED_SUMMARY_MODES: tuple[SummaryMode, ...] = ("default", "accurate", "oneshot")

STYLE_MAP: dict[str, str] = {
    "minimal": "Minimal notes focused on the most important points.",
    "detailed": "Detailed notes with examples, details, and supporting facts.",
    "academic": "Academic writing style with arguments, evidence, and citations when present.",
    "tutorial": "Step-by-step tutorial format with key actions and examples.",
    "meeting": "Meeting minutes with agenda, discussion points, decisions, and follow-ups.",
    "xiaohongshu": "Xiaohongshu-style notes with a lighter tone and stronger highlights.",
}

SUMMARY_MODE_MAP: dict[SummaryMode, dict[OutputLanguage, str]] = {
    "default": {
        "zh-CN": "默认模式：短内容一次性整理，长内容自动分段整理后再合并。",
        "en": "Default mode: short transcripts use one-shot summarization, long transcripts switch to hierarchical summarization.",
    },
    "accurate": {
        "zh-CN": "精确模式：先分段整理，再做全局合并，优先保证覆盖率和稳定性。",
        "en": "Accurate mode: summarize in chunks first, then merge globally for better coverage and stability.",
    },
    "oneshot": {
        "zh-CN": "一次性模式：把全部转录一次性交给模型，优先保留整体文风。",
        "en": "One-shot mode: send the full transcript to the model in one pass and preserve a single consistent writing style.",
    },
}

STYLE_INSTRUCTIONS: dict[OutputLanguage, dict[str, str]] = {
    "zh-CN": {
        "minimal": "风格要求：使用精简模式，只保留每个章节最核心的要点。",
        "detailed": "风格要求：使用详细模式，尽量完整记录内容、示例、结论和关键细节。",
        "academic": "风格要求：使用学术表达，整理论点、论据和原文中明确出现的引用关系。",
        "tutorial": "风格要求：使用教程模式，按步骤整理流程、方法和关键操作。",
        "meeting": "风格要求：按原文实际内容整理会议记录，保留发言人编号和 [MM:SS] 时间引用。议题、决策、待办、未决问题均为可选章节，原文没有就省略，禁止为了填满模板编造。只有原文明示要执行的任务才是待办；仅已有任务缺少负责人或日期时可标注待确认。播放演示或引用他人音频不代表其中的发言者在操作播放，也不代表正在开会或产生后续任务。区分建议、过程说明与已达成的决策，不把资料缺失改写成未决问题。",
        "xiaohongshu": "风格要求：使用小红书风格，语气更轻松，适度使用 emoji 和高亮表达。",
    },
    "en": {
        "minimal": "Style requirement: use a minimal format and keep only the core takeaways for each section.",
        "detailed": "Style requirement: use a detailed format and preserve examples, conclusions, and supporting details.",
        "academic": "Style requirement: use an academic tone and organize claims, evidence, and explicit references from the transcript.",
        "tutorial": "Style requirement: use a tutorial format and present the workflow as clear step-by-step guidance.",
        "meeting": "Style requirement: organize only the actual content, retaining speaker IDs and [MM:SS] references. Agenda, decisions, actions and open questions are optional; omit unsupported sections. An action requires an explicitly stated task; only an existing task's missing owner or date may be marked unconfirmed. Playback or quoted speech does not imply that the quoted speaker operated playback, attended a meeting or accepted a follow-up. Distinguish proposals and process narration from decisions. Missing information is not an open question.",
        "xiaohongshu": "Style requirement: use a Xiaohongshu-style tone with light emoji usage and stronger highlights.",
    },
}

SYSTEM_PROMPTS: dict[OutputLanguage, str] = {
    "zh-CN": """你是一名专业的视频笔记助手，负责把视频转录整理成结构清晰、信息准确的 Markdown 笔记。

语言要求：
- 笔记主体必须使用中文。
- 品牌名、专有名词、代码、接口名和原本就是英文的人名可以保留英文。

输出要求：
- 只返回最终 Markdown，不要包裹在代码块中。
- 不要把章节标题写成有序列表，使用标准 Markdown 标题层级。
- 数学公式使用 LaTeX 语法。

整理原则：
1. 严格基于转录内容，不要补充转录中没有明确出现的事实。
2. 可以重组语序、分段、添加小标题和列表，但不要改变原意。
3. 去掉寒暄、口头禅、重复和明显无关内容。
4. 保留关键事实、例子、步骤、结论和建议。
5. 仅在有明确时间依据且画面有助于理解时添加 [[Screenshot:MM:SS]]，不强行凑图。
6. 不推断未提供的画面内容，不将展示的建议写成已确认结论。
7. 发言时间范围严格使用输入的开始与结束时间，不把下一位说话人的开始时间当作上一段的结束时间。""",
    "en": """You are a professional video note assistant. Convert raw video transcripts into clear, accurate Markdown notes.

Language requirements:
- The note body must be written in English.
- Keep brand names, proper nouns, code, API names, and names that are already in another language when appropriate.

Output requirements:
- Return only the final Markdown content. Do not wrap it in a code block.
- Do not format section headings as numbered lists; use normal Markdown heading levels.
- Use LaTeX syntax for math expressions.

Editing principles:
1. Stay faithful to the transcript and do not invent facts that are not explicitly present.
2. You may reorganize sentences, paragraphs, headings, and lists, but do not change the meaning.
3. Remove greetings, filler words, repetition, and obviously irrelevant content.
4. Preserve important facts, examples, steps, conclusions, and recommendations.
5. Add [[Screenshot:MM:SS]] only when a supported timestamp and useful visual context exist; do not force screenshots.
6. Do not invent unseen visual content or treat a presented proposal as a confirmed decision.
7. Use the supplied start and end times for speaking turns; never substitute the next speaker's start time for a turn's end.""",
}

CHUNK_SYSTEM_PROMPTS: dict[OutputLanguage, str] = {
    "zh-CN": """你正在为长视频笔记生成中间整理稿。当前只处理其中一个片段块。

要求：
- 只基于当前片段块整理，不要推断片段外内容。
- 输出简洁、结构化的 Markdown 中间稿。
- 优先提取主题、关键观点、决定、行动项、风险、未决问题。
- 尽量保留时间点引用，例如 [12:34]。
- 不要写开场白、结束语，也不要生成最终的 AI 总结段落。""",
    "en": """You are producing an intermediate working draft for a long transcript.

Requirements:
- Use only the current chunk and do not infer facts outside it.
- Return concise, structured Markdown notes.
- Prioritize topics, key points, decisions, action items, risks, and open questions.
- Preserve timestamp references when possible, for example [12:34].
- Do not add greetings, closing remarks, or the final AI Summary section.""",
}

MERGE_SYSTEM_PROMPTS: dict[OutputLanguage, str] = {
    "zh-CN": """你正在把多个片段整理稿合并为最终视频笔记。

要求：
- 合并重复内容，统一结构和措辞。
- 保留关键决策、行动项、风险和重要细节。
- 如果不同片段讨论的是同一主题，合并到同一章节。
- 输出最终 Markdown，不要解释过程。""",
    "en": """You are merging multiple chunk-level drafts into the final transcript note.

Requirements:
- Deduplicate overlapping content and unify structure and wording.
- Preserve important decisions, action items, risks, and key details.
- Merge related chunks under the same topic when they cover the same subject.
- Return only the final Markdown output without explaining the process.""",
}

USER_PROMPT_TEMPLATES: dict[OutputLanguage, str] = {
    "zh-CN": """视频标题：{title}

视频分段转录（格式：时间 - 内容）：
---
{segment_text}
---

请根据上面的转录内容生成一份结构化视频笔记。
请在笔记末尾增加 **## AI 总结** 章节，用 3 到 5 句话概括视频核心内容。

{style_instruction}
{extras_instruction}""",
    "en": """Video title: {title}

Segmented transcript (format: timestamp - content):
---
{segment_text}
---

Please generate a structured video note from the transcript above.
Add a **## AI Summary** section at the end with 3 to 5 sentences summarizing the core ideas.

{style_instruction}
{extras_instruction}""",
}

CHUNK_USER_PROMPT_TEMPLATES: dict[OutputLanguage, str] = {
    "zh-CN": """视频标题：{title}

当前处理第 {chunk_index}/{chunk_total} 个转录片段块。

请基于下面这部分转录生成一份中间整理稿，供后续全局合并使用。
中间整理稿建议包含：
- 本片段主题
- 关键观点
- 决策 / 结论
- 行动项 / 待办
- 风险 / 未决问题

片段转录：
---
{segment_text}
---

{style_instruction}
{extras_instruction}""",
    "en": """Video title: {title}

You are processing transcript chunk {chunk_index}/{chunk_total}.

Generate an intermediate draft from this chunk for later global merging.
The draft should preferably capture:
- Chunk topics
- Key points
- Decisions / conclusions
- Action items / follow-ups
- Risks / open questions

Chunk transcript:
---
{segment_text}
---

{style_instruction}
{extras_instruction}""",
}

MERGE_USER_PROMPT_TEMPLATES: dict[OutputLanguage, str] = {
    "zh-CN": """视频标题：{title}

下面是按片段生成的中间整理稿，请把它们合并成最终笔记。

合并要求：
- 去重并合并相邻主题
- 保留关键事实、例子、步骤、决策和待办
- 不要遗漏跨片段出现的重要结论
- 在笔记末尾增加 **## AI 总结** 章节，用 3 到 5 句话概括核心内容

中间整理稿：
---
{chunk_notes_text}
---

{style_instruction}
{extras_instruction}""",
    "en": """Video title: {title}

Below are intermediate chunk drafts. Merge them into the final note.

Requirements:
- Deduplicate and merge adjacent topics
- Preserve important facts, examples, steps, decisions, and follow-ups
- Do not lose important conclusions that appear across chunks
- Add a **## AI Summary** section at the end with 3 to 5 sentences summarizing the core ideas

Chunk drafts:
---
{chunk_notes_text}
---

{style_instruction}
{extras_instruction}""",
}


def normalize_output_language(output_language: str | None) -> OutputLanguage:
    if output_language == "en":
        return "en"
    return DEFAULT_OUTPUT_LANGUAGE


def normalize_summary_mode(summary_mode: str | None) -> SummaryMode:
    if summary_mode in SUPPORTED_SUMMARY_MODES:
        return summary_mode
    return DEFAULT_SUMMARY_MODE


def _build_style_instruction(style: str, language: OutputLanguage) -> str:
    return STYLE_INSTRUCTIONS[language].get(style, STYLE_INSTRUCTIONS[language]["detailed"])


def _build_extras_instruction(extras: str | None, language: OutputLanguage) -> str:
    if not extras:
        return ""
    if language == "zh-CN":
        return f"额外要求：{extras}"
    return f"Additional requirements: {extras}"


def build_system_prompt(output_language: str | None = None) -> str:
    language = normalize_output_language(output_language)
    return SYSTEM_PROMPTS[language]


def build_chunk_system_prompt(output_language: str | None = None) -> str:
    language = normalize_output_language(output_language)
    return CHUNK_SYSTEM_PROMPTS[language]


def build_merge_system_prompt(output_language: str | None = None) -> str:
    language = normalize_output_language(output_language)
    return MERGE_SYSTEM_PROMPTS[language]


def build_user_prompt(
    title: str,
    segment_text: str,
    style: str = "detailed",
    extras: str | None = None,
    output_language: str | None = None,
) -> str:
    language = normalize_output_language(output_language)
    return USER_PROMPT_TEMPLATES[language].format(
        title=title,
        segment_text=segment_text,
        style_instruction=_build_style_instruction(style, language),
        extras_instruction=_build_extras_instruction(extras, language),
    )


def build_chunk_user_prompt(
    title: str,
    segment_text: str,
    chunk_index: int,
    chunk_total: int,
    style: str = "detailed",
    extras: str | None = None,
    output_language: str | None = None,
) -> str:
    language = normalize_output_language(output_language)
    return CHUNK_USER_PROMPT_TEMPLATES[language].format(
        title=title,
        segment_text=segment_text,
        chunk_index=chunk_index,
        chunk_total=chunk_total,
        style_instruction=_build_style_instruction(style, language),
        extras_instruction=_build_extras_instruction(extras, language),
    )


def build_merge_user_prompt(
    title: str,
    chunk_notes_text: str,
    style: str = "detailed",
    extras: str | None = None,
    output_language: str | None = None,
) -> str:
    language = normalize_output_language(output_language)
    return MERGE_USER_PROMPT_TEMPLATES[language].format(
        title=title,
        chunk_notes_text=chunk_notes_text,
        style_instruction=_build_style_instruction(style, language),
        extras_instruction=_build_extras_instruction(extras, language),
    )
