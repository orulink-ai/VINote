import unittest

from app.llm.openai_llm import _BasePromptLLM
from app.models.transcript import TranscriptSegment


class RecordingLLM(_BasePromptLLM):
    def __init__(self):
        self.calls: list[dict[str, str]] = []

    def _complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        if "Chunk drafts:" in user_prompt or "中间整理稿：" in user_prompt:
            return "# Final Note"
        return "## Chunk Note\n- item"


class SummaryModeStrategyTest(unittest.TestCase):
    def test_oneshot_mode_uses_single_generation(self):
        llm = RecordingLLM()
        result = llm.summarize(
            title="Demo",
            segments=[TranscriptSegment(start=0.0, end=1.0, text="hello world")],
            summary_mode="oneshot",
            output_language="en",
        )

        self.assertEqual(result, "## Chunk Note\n- item")
        self.assertEqual(len(llm.calls), 1)

    def test_accurate_mode_uses_chunk_then_merge(self):
        llm = RecordingLLM()
        segments = [
            TranscriptSegment(start=float(index), end=float(index + 1), text="x" * 4000)
            for index in range(4)
        ]
        progress: list[str] = []

        result = llm.summarize(
            title="Long Demo",
            segments=segments,
            summary_mode="accurate",
            output_language="en",
            progress_callback=progress.append,
        )

        self.assertEqual(result, "# Final Note")
        self.assertGreaterEqual(len(llm.calls), 3)
        self.assertTrue(any("chunk notes" in item for item in progress))
        self.assertTrue(any("Combining chunk notes" in item for item in progress))

    def test_default_mode_keeps_full_input_in_one_generation(self):
        llm = RecordingLLM()
        segments = [
            TranscriptSegment(start=float(index), end=float(index + 1), text="y" * 5000)
            for index in range(4)
        ]

        llm.summarize(
            title="Auto Demo",
            segments=segments,
            summary_mode="default",
            output_language="en",
        )

        self.assertEqual(len(llm.calls), 1)
        for segment in segments:
            self.assertIn(segment.text, llm.calls[0]['user_prompt'])


if __name__ == "__main__":
    unittest.main()
