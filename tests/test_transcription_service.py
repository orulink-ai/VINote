import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.models.stt_profile import ResolvedSTTConfig
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.transcription_service import ChunkSpec, TranscriptionService, create_transcriber


class FakeSTTProfileService:
    def __init__(self):
        self.calls: list[tuple[str | None, str | None]] = []
        self.configs = {
            "profile-1": ResolvedSTTConfig(provider="whisper", model_name="base", device="cpu"),
            "profile-2": ResolvedSTTConfig(provider="faster-whisper", model_name="large-v3", device="cuda", compute_type="float16"),
        }

    def resolve_config(self, *, user_id: str | None, stt_profile_id: str | None):
        self.calls.append((user_id, stt_profile_id))
        return self.configs[stt_profile_id]


class FakeTranscriber:
    def __init__(self, marker: str):
        self.marker = marker

    def transcribe(self, file_path: str):
        return TranscriptResult(
            language="en",
            full_text=self.marker,
            segments=[TranscriptSegment(start=0.0, end=1.0, text=self.marker)],
        )


class TranscriptionServiceTest(unittest.TestCase):
    def test_cloud_bounds_cover_three_hours_even_when_chunking_disabled(self):
        from app.config import settings
        from app.transcribers.vilab_transcriber import VILabTranscriber
        service = TranscriptionService()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "compressed.mp3"
            source.write_bytes(b"small compressed input")
            for enabled in (True, False):
                with patch.object(settings, "transcription_chunking_enabled", enabled):
                    chunks = service._build_chunk_specs(
                        audio_path=str(source), duration=10800, temp_dir=Path(directory),
                        request_duration_limit=VILabTranscriber.max_request_duration_seconds)
                self.assertGreater(len(chunks), 1)
                self.assertEqual(chunks[0].trim_start, 0)
                self.assertEqual(chunks[-1].trim_end, 10800)
                for chunk in chunks:
                    self.assertLessEqual(chunk.chunk_end - chunk.chunk_start, 300)
                for previous, current in zip(chunks, chunks[1:]):
                    self.assertEqual(previous.trim_end, current.trim_start)

    def test_cloud_limit_is_applied_by_actual_orchestrator(self):
        from app.transcribers.vilab_transcriber import VILabTranscriber
        service = TranscriptionService()
        with patch.object(service, "_build_chunk_specs", return_value=[]) as specs, \
                patch.object(service, "_transcribe_chunk", return_value=TranscriptResult(None, "ok", [])):
            service._transcribe_in_chunks(audio_path="test.wav", duration=60,
                                         transcriber=VILabTranscriber("http://localhost", "test"))
            self.assertEqual(specs.call_args.kwargs["request_duration_limit"], 300)

    def test_explicit_silent_chunk_preserves_other_speech_and_offsets(self):
        from app.models.transcript import NoSpeechDetectedError
        service = TranscriptionService()
        chunk = ChunkSpec(1, 2, Path("silent.wav"), 0, 35, 0, 30)
        adapter = FakeTranscriber("unused")
        with patch.object(adapter, "transcribe", side_effect=NoSpeechDetectedError("no speech")):
            empty = service._transcribe_chunk(adapter, "silent.wav", chunk)
        speech = TranscriptResult("zh", "有效发言", [TranscriptSegment(5, 10, "有效发言")],
                                  metadata={"timestamp_granularity": "segment"})
        merged = service._merge_chunk_results(chunk_results=[
            (chunk, empty), (ChunkSpec(2, 2, Path("speech.wav"), 25, 60, 30, 60), speech)])
        self.assertEqual(merged.full_text, "有效发言")
        self.assertEqual(merged.segments[0].start, 30)
        self.assertEqual(merged.metadata["unrecognized_segments"][0]["end"], 30)
        self.assertEqual(merged.metadata["timestamp_granularity"], "segment")

    def test_whole_audio_result_survives_later_pipeline_failure(self):
        service = TranscriptionService()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "recording.wav"
            source.write_bytes(b"same-recording")
            result = TranscriptResult(language="en", full_text="hello", segments=[])
            updates = []
            arguments = dict(audio_path=str(source), duration=60, transcriber=FakeTranscriber("test"),
                             chunk_cache_dir=Path(directory) / "cache", cache_identity="model-a",
                             update_status=lambda status, message, **details: updates.append(details))
            with patch.object(service, "_build_chunk_specs", return_value=[]), \
                    patch.object(service, "_transcribe_chunk", return_value=result) as call:
                service._transcribe_in_chunks(**arguments)
                service._transcribe_in_chunks(**arguments)
                self.assertEqual(call.call_count, 1)
                self.assertEqual(updates[-1]["processed_seconds"], 60)
                self.assertIsNone(updates[-1]["eta_seconds"])
                source.write_bytes(b"different-recording")
                service._transcribe_in_chunks(**arguments)
                self.assertEqual(call.call_count, 2)

    def test_retry_reuses_successful_chunks_after_later_cloud_failure(self):
        service = TranscriptionService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunks = [ChunkSpec(1, 2, root / "first.wav", 0, 30, 0, 30),
                      ChunkSpec(2, 2, root / "second.wav", 30, 60, 30, 60)]
            for chunk in chunks:
                chunk.file_path.write_bytes(str(chunk.index).encode())
            result = TranscriptResult(language="en", full_text="hello", segments=[])
            arguments = dict(audio_path="original.wav", duration=60, transcriber=FakeTranscriber("test"),
                             chunk_cache_dir=root / "cache", cache_identity="model-a")
            with patch.object(service, "_build_chunk_specs", return_value=chunks), patch.object(service, "_extract_chunk"):
                with patch.object(service, "_transcribe_chunk", side_effect=[result, RuntimeError("cloud failed")]):
                    with self.assertRaisesRegex(RuntimeError, "cloud failed"):
                        service._transcribe_in_chunks(**arguments)
                with patch.object(service, "_transcribe_chunk", return_value=result) as call:
                    service._transcribe_in_chunks(**arguments)
                    self.assertEqual(call.call_count, 1)
                    self.assertEqual(call.call_args.args[1], str(chunks[1].file_path))
                with patch.object(service, "_transcribe_chunk", return_value=result) as call:
                    service._transcribe_in_chunks(**{**arguments, "cache_identity": "model-b"})
                    self.assertEqual(call.call_count, 2)

    def test_chunk_progress_counts_core_offsets_and_estimates_from_elapsed_time(self):
        service = TranscriptionService()
        chunks = [ChunkSpec(1, 2, Path("first.wav"), 0, 35, 0, 30),
                  ChunkSpec(2, 2, Path("second.wav"), 25, 60, 30, 60)]
        updates = []
        result = TranscriptResult(language="en", full_text="hello", segments=[])
        with patch.object(service, "_build_chunk_specs", return_value=chunks), \
                patch.object(service, "_extract_chunk"), \
                patch.object(service, "_transcribe_chunk", return_value=result), \
                patch("app.services.transcription_service.time.monotonic", side_effect=[0, 10, 10, 20]):
            service._transcribe_in_chunks(
                audio_path="recording.wav", duration=60, transcriber=FakeTranscriber("test"),
                update_status=lambda status, message, **details: updates.append(details))
        self.assertEqual([item["processed_seconds"] for item in updates], [0, 30, 30, 60])
        self.assertEqual([item["progress"] for item in updates], [0, .5, .5, 1])
        self.assertIsNone(updates[0]["eta_seconds"])
        self.assertEqual(updates[1]["eta_seconds"], 10)
        self.assertEqual(updates[-1]["eta_seconds"], 0)

    def test_create_transcriber_explains_missing_openai_whisper_dependency(self):
        config = ResolvedSTTConfig(provider="whisper", model_name="base", device="cpu")

        with patch("app.services.transcription_service.importlib.util.find_spec", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "pip install openai-whisper"):
                create_transcriber(config)

    def test_create_transcriber_explains_missing_faster_whisper_dependency(self):
        config = ResolvedSTTConfig(provider="faster-whisper", model_name="base", device="cpu", compute_type="int8")

        with patch("app.services.transcription_service.importlib.util.find_spec", return_value=object()):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'faster_whisper'")):
                with self.assertRaisesRegex(RuntimeError, "requirements.local-transcribers.txt"):
                    create_transcriber(config)

    def test_transcribe_uses_selected_profile_per_task(self):
        fake_profile_service = FakeSTTProfileService()
        created_models: list[str] = []

        def fake_create_transcriber(config: ResolvedSTTConfig):
            marker = config.model_name or config.provider
            created_models.append(marker)
            return FakeTranscriber(marker)

        service = TranscriptionService(stt_profile_service=fake_profile_service)

        with patch("app.services.transcription_service.create_transcriber", side_effect=fake_create_transcriber), patch.object(
            service,
            "get_audio_duration",
            return_value=0.0,
        ):
            first = service.transcribe(
                audio_path="audio.mp3",
                load_cached=lambda: None,
                save_transcript=lambda result: None,
                user_id="user-1",
                stt_profile_id="profile-1",
            )
            second = service.transcribe(
                audio_path="audio.mp3",
                load_cached=lambda: None,
                save_transcript=lambda result: None,
                user_id="user-1",
                stt_profile_id="profile-2",
            )

        self.assertEqual(fake_profile_service.calls, [("user-1", "profile-1"), ("user-1", "profile-2")])
        self.assertEqual(created_models, ["base", "large-v3"])
        self.assertEqual(first.full_text, "base")
        self.assertEqual(second.full_text, "large-v3")


if __name__ == "__main__":
    unittest.main()
