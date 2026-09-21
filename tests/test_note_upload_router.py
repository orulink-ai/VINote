import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import note
from app.services.task_artifact_service import TaskArtifactService


class GenerateFromUploadRouterTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name) / "outputs"
        self.artifact_service = TaskArtifactService(output_dir=self.output_dir)
        self.app = FastAPI()
        self.app.include_router(note.router, prefix="/api")
        self.client = TestClient(self.app)

    def tearDown(self):
        note._ACTIVE_FILE_TASKS.clear()
        self.temp_dir.cleanup()

    def test_recording_artifacts_require_owner_or_accessible_note(self):
        task = self.artifact_service.create_task_dir("private-recording")
        self.artifact_service.update_status(task, "uploaded", "Saved")
        (task / "recording_owner").write_text("owner", encoding="utf-8")
        (task / "media").mkdir()
        (task / "media" / "source_audio.wav").write_bytes(b"private-audio")
        url = "/api/task/private-recording/artifacts/media/source_audio.wav"
        with patch.object(note, "_note_service", SimpleNamespace(artifact_service=self.artifact_service)):
            self.app.dependency_overrides[note.get_optional_current_user] = lambda: None
            self.assertEqual(self.client.get(url).status_code, 404)
            self.app.dependency_overrides[note.get_optional_current_user] = lambda: SimpleNamespace(user_id="owner")
            self.assertEqual(self.client.get(url).content, b"private-audio")
            self.app.dependency_overrides[note.get_optional_current_user] = lambda: SimpleNamespace(user_id="member")
            with patch("app.services.note_repository.NoteRepository.can_access_task", return_value=False):
                self.assertEqual(self.client.get(url).status_code, 404)
            with patch("app.services.note_repository.NoteRepository.can_access_task", return_value=True):
                self.assertEqual(self.client.get(url).content, b"private-audio")

    def test_retry_checks_owner_and_reuses_active_task(self):
        self.app.dependency_overrides[note.get_current_user] = lambda: SimpleNamespace(user_id="owner")
        task = self.artifact_service.create_task_dir("retry-task")
        self.artifact_service.update_status(task, "failed", "cloud unavailable")
        (task / "recording_owner").write_text("other", encoding="utf-8")
        fake = SimpleNamespace(artifact_service=self.artifact_service)
        with patch.object(note, "_note_service", fake):
            self.assertEqual(self.client.post("/api/task/retry-task/retry").status_code, 404)
            (task / "recording_owner").write_text("owner", encoding="utf-8")
            self.assertEqual(self.client.post("/api/task/retry-task/retry").status_code, 409)
            note._ACTIVE_FILE_TASKS.add("retry-task")
            try:
                with patch.object(note, "_run_task_from_file") as run:
                    response = self.client.post("/api/task/retry-task/retry")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["task_id"], "retry-task")
                    run.assert_not_called()
            finally:
                note._ACTIVE_FILE_TASKS.discard("retry-task")

    def test_repeated_meeting_upload_reuses_task_after_lost_response(self):
        self.app.dependency_overrides[note.get_optional_current_user] = lambda: SimpleNamespace(user_id="owner")
        with patch.object(note, "_note_service", SimpleNamespace(artifact_service=self.artifact_service)), patch.object(note, "_run_task_from_file") as run:
            arguments = dict(data={"source_type": "audio", "workflow": "meeting", "meeting_session_id": "recording-123"},
                             files={"file": ("recording.wav", b"audio", "audio/wav")})
            first = self.client.post("/api/generate_from_upload", **arguments)
            repeated = self.client.post("/api/generate_from_upload", **arguments)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(repeated.status_code, 200, repeated.text)
            self.assertEqual(first.json()["task_id"], repeated.json()["task_id"])
        self.assertEqual(run.call_count, 1)
        # Reservation must exist before the scheduled worker starts.
        self.assertIn(first.json()["task_id"], note._ACTIVE_FILE_TASKS)

    def test_generate_from_upload_preserves_audio_before_background_processing(self):
        fake_note_service = SimpleNamespace(artifact_service=self.artifact_service)

        with patch.object(note, "_note_service", fake_note_service), patch.object(note, "_run_task_from_file") as run_task:
            response = self.client.post(
                "/api/generate_from_upload",
                data={
                    "title": "Meeting recording",
                    "style": "meeting",
                    "summary_mode": "default",
                    "source_type": "audio",
                    "output_language": "zh-CN",
                },
                files={"file": ("meeting.webm", b"audio-bytes", "audio/webm")},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "uploaded")
        saved_request = json.loads((self.output_dir / payload["task_id"] / "request.json").read_text(encoding="utf-8"))
        self.assertEqual(saved_request["request"]["title"], "Meeting recording")
        self.assertNotIn("api_key", saved_request["request"])
        task_id = payload["task_id"]
        audio_path = self.output_dir / task_id / "media" / "source_audio.webm"
        self.assertEqual(audio_path.read_bytes(), b"audio-bytes")
        manifest_path = self.output_dir / task_id / "source_media.json"
        self.assertTrue(manifest_path.is_file())
        self.assertEqual(
            self.artifact_service.resolve_source_media(self.output_dir / task_id),
            audio_path.resolve(),
        )
        self.assertEqual(self.artifact_service.get_status(task_id)["status"], "uploaded")
        run_task.assert_called_once()
        _, kwargs = run_task.call_args
        self.assertEqual(kwargs["task_id"], task_id)
        self.assertEqual(kwargs["req"].file_path, str(audio_path))
        self.assertEqual(kwargs["req"].title, "Meeting recording")
        self.assertFalse(kwargs["req"].diarize)

    def test_transcript_upload_ignores_legacy_live_attachment(self):
        self.app.dependency_overrides[note.get_optional_current_user] = lambda: SimpleNamespace(user_id="user-test")
        fake_service = SimpleNamespace(artifact_service=self.artifact_service)
        with patch.object(note, "_note_service", fake_service), patch.object(note, "_run_task_from_transcript") as run:
            response = self.client.post("/api/generate_from_upload", data={"source_type": "transcript"},
                files={"file": ("speech.txt", b"Meeting discussion", "text/plain"),
                       "recording": ("meeting.webm", b"original-audio", "audio/webm")})
        self.assertEqual(response.status_code, 200, response.text)
        task_dir = self.output_dir / response.json()["task_id"]
        self.assertFalse((task_dir / "media/source_audio.webm").exists())
        run.assert_called_once()

    def test_desktop_media_upload_always_uses_automatic_diarization(self):
        fake_note_service = SimpleNamespace(artifact_service=self.artifact_service)

        with patch.object(note, "_note_service", fake_note_service), \
                patch.object(note, "_run_task_from_file") as run_task, \
                patch("app.services.speaker_diarization_service.SpeakerDiarizationService.require_ready"):
            response = self.client.post(
                "/api/generate_from_upload",
                headers={"X-VINote-Client": "desktop"},
                data={"source_type": "audio", "diarize": "false", "speaker_count": "12"},
                files={"file": ("discussion.wav", b"audio-bytes", "audio/wav")},
            )

        self.assertEqual(response.status_code, 200)
        req = run_task.call_args.kwargs["req"]
        self.assertTrue(req.diarize)
        self.assertIsNone(req.speaker_count)

    def test_desktop_video_url_always_uses_automatic_diarization(self):
        with patch.object(note, "_run_task") as run_task:
            response = self.client.post(
                "/api/generate",
                headers={"X-VINote-Client": " Desktop "},
                json={
                    "video_url": "https://example.test/video",
                    "workflow": "note_organization",
                    "diarize": False,
                    "speaker_count": 8,
                },
            )

        self.assertEqual(response.status_code, 200)
        req = run_task.call_args.kwargs["req"]
        self.assertTrue(req.diarize)
        self.assertIsNone(req.speaker_count)

    def test_json_transcript_keeps_speaker_text_variants_and_provenance(self):
        transcript = note._build_transcript_from_json(
            json.dumps(
                {
                    "language": "zh",
                    "full_text": "清洗文本",
                    "metadata": {"asr_model": "external-asr", "diarization": "external-speaker"},
                    "segments": [
                        {
                            "start": 1.5,
                            "end": 4.0,
                            "text": "清洗文本",
                            "raw_text": "原始 文本",
                            "cleaned_text": "清洗文本",
                            "speaker_id": "speaker_01",
                            "speaker_label": "Speaker 1",
                        }
                    ],
                }
            ),
            "meeting.json",
        )

        self.assertEqual(transcript.metadata["asr_model"], "external-asr")
        self.assertEqual(transcript.segments[0].speaker_id, "speaker_01")
        self.assertEqual(transcript.segments[0].raw_text, "原始 文本")


if __name__ == "__main__":
    unittest.main()
