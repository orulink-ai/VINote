import unittest

from app.llm.prompts import (
    build_chunk_user_prompt,
    build_merge_user_prompt,
    build_system_prompt,
    build_user_prompt,
    normalize_output_language,
    normalize_summary_mode,
)


class PromptBuilderTest(unittest.TestCase):
    def test_normalize_output_language_defaults_to_chinese(self):
        self.assertEqual(normalize_output_language(None), "zh-CN")
        self.assertEqual(normalize_output_language("unexpected"), "zh-CN")
        self.assertEqual(normalize_output_language("en"), "en")

    def test_normalize_summary_mode_defaults_to_default(self):
        self.assertEqual(normalize_summary_mode(None), "default")
        self.assertEqual(normalize_summary_mode("unexpected"), "default")
        self.assertEqual(normalize_summary_mode("accurate"), "accurate")
        self.assertEqual(normalize_summary_mode("oneshot"), "oneshot")

    def test_build_system_prompt_changes_with_language(self):
        chinese_prompt = build_system_prompt("zh-CN")
        english_prompt = build_system_prompt("en")

        self.assertIn("笔记主体必须使用中文", chinese_prompt)
        self.assertIn("must be written in English", english_prompt)

    def test_build_user_prompt_localizes_summary_title_and_extras(self):
        chinese_prompt = build_user_prompt(
            title="示例",
            segment_text="00:00 - 内容",
            style="detailed",
            extras="保留术语",
            output_language="zh-CN",
        )
        english_prompt = build_user_prompt(
            title="Example",
            segment_text="00:00 - Content",
            style="detailed",
            extras="Keep terms",
            output_language="en",
        )

        self.assertIn("## AI 总结", chinese_prompt)
        self.assertIn("额外要求：保留术语", chinese_prompt)
        self.assertIn("## AI Summary", english_prompt)
        self.assertIn("Additional requirements: Keep terms", english_prompt)

    def test_chunk_and_merge_prompts_include_processing_context(self):
        chunk_prompt = build_chunk_user_prompt(
            title="Demo",
            segment_text="00:00 - Hello",
            chunk_index=2,
            chunk_total=4,
            style="meeting",
            output_language="en",
        )
        merge_prompt = build_merge_user_prompt(
            title="Demo",
            chunk_notes_text="## Chunk Draft 1\n- hello",
            style="meeting",
            output_language="en",
        )

        self.assertIn("chunk 2/4", chunk_prompt)
        self.assertIn("Chunk drafts:", merge_prompt)
        self.assertNotIn("## AI Summary", merge_prompt)
        self.assertIn("Paused recording duration", chunk_prompt)
        self.assertIn("Paused recording duration", merge_prompt)


if __name__ == "__main__":
    unittest.main()
