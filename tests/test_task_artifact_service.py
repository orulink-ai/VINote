import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import json
from pathlib import Path

from app.models.audio import AudioDownloadResult
from app.models.note import NoteResult
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.task_artifact_service import TaskArtifactService


class TaskArtifactServiceTest(unittest.TestCase):
    def test_status_replace_retries_transient_windows_permission_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TaskArtifactService(Path(temp_dir))
            task_dir = service.create_task_dir("task-retry")

            with (
                patch(
                    "app.services.task_artifact_service.os.replace",
                    side_effect=[PermissionError("busy"), None],
                ) as replace,
                patch("app.services.task_artifact_service.time.sleep") as sleep,
            ):
                service.update_status(task_dir, "transcribing", "Transcribing audio...")

            self.assertEqual(replace.call_count, 2)
            sleep.assert_called_once_with(0.01)
            self.assertFalse(list(task_dir.glob(".status.json.*.tmp")))

    def test_status_polling_and_updates_do_not_race(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TaskArtifactService(Path(temp_dir))
            task_dir = service.create_task_dir("task-concurrent")
            service.update_status(task_dir, "preparing")
            start = threading.Event()

            def write_statuses() -> None:
                start.wait()
                for index in range(100):
                    service.update_status(task_dir, "transcribing", str(index))

            def read_statuses() -> None:
                start.wait()
                for _ in range(200):
                    payload = service.get_status("task-concurrent")
                    self.assertIn(payload["status"], {"preparing", "transcribing"})

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(write_statuses)]
                futures.extend(executor.submit(read_statuses) for _ in range(4))
                start.set()
                for future in futures:
                    future.result()

            self.assertEqual(service.get_status("task-concurrent")["message"], "99")
            self.assertFalse(list(task_dir.glob(".status.json.*.tmp")))

    def test_truncated_title_is_windows_safe_and_mapping_survives(self):
        with tempfile.TemporaryDirectory() as root:
            service = TaskArtifactService(Path(root))
            original = service.create_task_dir("task-space")
            service.update_status(original, "downloading")
            final = service.finalize_task_dir(original, "x" * 49 + " more", "task-space")
            self.assertFalse(final.name.endswith((" ", ".")))
            self.assertEqual(service.find_task_dir("task-space"), final)
            self.assertEqual(service.sanitize_filename("..."), "note")

    def test_mapping_write_failure_does_not_move_task(self):
        with tempfile.TemporaryDirectory() as root:
            service = TaskArtifactService(Path(root))
            original = service.create_task_dir("task-error")
            service.update_status(original, "downloading")
            with patch.object(service, "write_text", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    service.finalize_task_dir(original, "Title", "task-error")
            self.assertTrue(original.exists())
            self.assertEqual(service.find_task_dir("task-error"), original)

    def test_status_and_result_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TaskArtifactService(Path(temp_dir))
            task_dir = service.create_task_dir("task-123")
            service.update_status(task_dir, "downloading", "Downloading audio...")

            final_dir = service.finalize_task_dir(task_dir, 'Demo:Title*?', "task-123")
            transcript = TranscriptResult(
                language="zh",
                full_text="hello world",
                segments=[TranscriptSegment(start=0.0, end=1.0, text="hello world")],
                metadata={"provider": "local"},
            )
            audio_meta = AudioDownloadResult(
                file_path="demo.mp3",
                title="Demo Title",
                duration=12.5,
                video_id="video-1",
                platform="youtube",
                cover_url=None,
                raw_info={},
            )
            result = NoteResult(
                markdown="# Demo",
                transcript=transcript,
                audio_meta=audio_meta,
                output_dir=str(final_dir),
            )

            service.save_transcript(final_dir, transcript)
            service.save_result(final_dir, result)
            service.update_status(final_dir, "success", "Done")

            loaded_transcript = service.load_transcript(final_dir)
            self.assertIsNotNone(loaded_transcript)
            self.assertEqual(loaded_transcript.full_text, "hello world")
            self.assertEqual(loaded_transcript.metadata, {"provider": "local"})

            status_payload = service.get_status("task-123")
            result_payload = service.get_result("task-123")

            self.assertEqual(status_payload["status"], "success")
            self.assertEqual(status_payload["message"], "Done")
            self.assertEqual(result_payload["title"], "Demo Title")
            self.assertEqual(result_payload["output_path"], str(final_dir))
            self.assertIn("DemoTitle", final_dir.name)

    def test_stage_media_file_copies_into_media_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TaskArtifactService(Path(temp_dir))
            task_dir = service.create_task_dir("task-stage")
            source_file = Path(temp_dir) / "source.mp4"
            source_file.write_bytes(b"video")

            staged = service.stage_media_file(task_dir, str(source_file), target_stem="source_video")

            self.assertTrue(staged.exists())
            self.assertEqual(staged.parent.name, "media")
            self.assertEqual(staged.read_bytes(), b"video")

    def test_source_media_manifest_preserves_exact_bytes_and_rejects_escape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TaskArtifactService(Path(temp_dir) / "output")
            task_dir = service.create_task_dir("task-source")
            source_file = Path(temp_dir) / "meeting.webm"
            original_bytes = b"\x1aE\xdf\xa3original-recorder-bytes"
            source_file.write_bytes(original_bytes)

            staged = service.stage_source_media(task_dir, str(source_file), media_kind="audio")
            manifest = json.loads((task_dir / "source_media.json").read_text(encoding="utf-8"))

            self.assertEqual(staged.read_bytes(), original_bytes)
            self.assertEqual(manifest["relative_path"], "media/source_audio.webm")
            self.assertEqual(manifest["media_kind"], "audio")
            self.assertEqual(manifest["size_bytes"], len(original_bytes))
            self.assertEqual(service.resolve_source_media(task_dir), staged.resolve())

            staged.write_bytes(b"tampered")
            self.assertIsNone(service.resolve_source_media(task_dir))
            staged.write_bytes(original_bytes)

            escaped = Path(temp_dir) / "outside.webm"
            escaped.write_bytes(b"outside")
            (task_dir / "source_media.json").write_text(
                json.dumps({"relative_path": "../../outside.webm"}),
                encoding="utf-8",
            )
            self.assertIsNone(service.resolve_source_media(task_dir))


if __name__ == "__main__":
    unittest.main()
