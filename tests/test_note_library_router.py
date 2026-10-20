import tempfile
import json
import uuid
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.db_models import TeamDB, TeamMemberDB
from app.models.auth import AuthenticatedUser
from app.models.audio import AudioDownloadResult
from app.models.note_library import NoteCreateRequest
from app.models.local_file import LocalFileDB  # Register retention tables before the isolated create_all.
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.routers import note_library
from app.services.auth_service import get_current_user
from app.services.note_repository import NoteRepository
from app.services.task_artifact_service import TaskArtifactService


class MeetingSourceProjectionTest(unittest.TestCase):
    """Synthetic metadata only: no live storage, provider or media processing."""

    def test_owner_bound_canonical_projection_and_fail_closed_counterexamples(self):
        from app.models.note_library import NoteRecordResponse
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as temporary:
            artifacts = TaskArtifactService(Path(temporary))
            parent, child, sibling = (str(uuid.uuid4()) for _ in range(3))
            for task in (parent, child, sibling):
                folder = artifacts.create_task_dir(task)
                (folder / '.task_id').write_text(task, encoding='utf-8')
                (folder / 'recording_owner').write_text('owner-a', encoding='utf-8')
                artifacts.write_json(folder / 'request.json', {'request': {'workflow': 'meeting'}})
            canonical = artifacts.find_task_dir(parent)
            artifacts.write_json(canonical / 'source_media.json', {'sha256': 'a' * 64,
                'relative_path': 'media/source_audio.wav', 'size_bytes': 12, 'media_kind': 'audio'})
            for task in (child, sibling):
                artifacts.write_json(artifacts.find_task_dir(task) / 'source_reference.json', {
                    'version': 1, 'owner': 'owner-a', 'parent_task_id': parent, 'source_version': 'a' * 64})
            now = datetime.now(timezone.utc)
            notes = [NoteRecordResponse(id=task, task_id=task, title='相同标题', content='保留正文',
                status='done', source_type='meeting_recording', created_at=now, updated_at=now)
                for task in (parent, child, sibling)]
            app = FastAPI()
            app.include_router(note_library.router, prefix='/api')
            app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(user_id='owner-a')
            with TestClient(app) as client, patch.object(note_library, '_artifact_service', artifacts), \
                    patch.object(note_library._repository, 'list_notes', return_value=notes), \
                    patch.object(note_library._repository, 'get_note', return_value=notes[1]):
                def read():
                    response = client.get('/api/notes')
                    self.assertEqual(response.status_code, 200)
                    return response.json()

                expected = {'owner_id': 'owner-a', 'canonical_task_id': parent, 'recording_started_at': None}
                before = {str(p): p.read_bytes() for p in Path(temporary).rglob('*') if p.is_file()}
                self.assertEqual([n.get('meeting_source') for n in read()], [expected] * 3)
                self.assertEqual(client.get('/api/notes/child').json().get('meeting_source'), expected)
                # Saving/editing replaces the in-memory row immediately: its
                # response must retain provenance without a list refresh.
                with patch.object(note_library._repository, 'create_note', return_value=notes[1]), \
                        patch.object(note_library._repository, 'update_note', return_value=notes[1]):
                    self.assertEqual(client.post('/api/notes', json={'title': '人工R2', 'task_id': child}).json().get('meeting_source'), expected)
                    self.assertEqual(client.patch('/api/notes/child', json={'content': '人工R2'}).json().get('meeting_source'), expected)
                # Missing original media is not missing saved text or its proven relation.
                self.assertFalse((canonical / 'media/source_audio.wav').exists())
                self.assertEqual(before, {str(p): p.read_bytes() for p in Path(temporary).rglob('*') if p.is_file()})

                # A summary child reads the original's explicit capture clock,
                # never its own generated title or current save time.
                artifacts.write_json(canonical / 'request.json', {
                    'request': {'workflow': 'meeting', 'extras': '录制开始时间：2026-01-03T02:04:05.123Z。录制结束时间：2026-01-03T03:00:00Z。'},
                    'trace': {'source': 'desktop_recording', 'session_id': 'rec-123-abc',
                        'input': {'source': 'desktop_recording', 'workflow': 'meeting',
                            'recording_id': 'rec-123-abc', 'filename': 'meeting-recording-2026-01-03-02-04-05.webm'}}})
                projected = read()
                self.assertTrue(all(n['meeting_source']['recording_started_at'] == '2026-01-03T02:04:05.123000Z' for n in projected))

                child_folder = artifacts.find_task_dir(child)
                reference_path = child_folder / 'source_reference.json'
                valid = json.loads(reference_path.read_text(encoding='utf-8'))
                for update in ({'owner': 'other'}, {'parent_task_id': child},
                               {'source_version': 'b' * 64}, {'parent_task_id': '../escape'},
                               {'parent_task_id': sibling}, {'extra': True}):
                    artifacts.write_json(reference_path, {**valid, **update})
                    self.assertIsNone(read()[1].get('meeting_source'), update)
                    self.assertEqual(read()[1]['content'], '保留正文')
                artifacts.write_json(reference_path, valid)
                (child_folder / 'recording_owner').write_text('other', encoding='utf-8')
                self.assertIsNone(read()[1].get('meeting_source'))
                (child_folder / 'recording_owner').write_text('owner-a', encoding='utf-8')
                (child_folder / '.task_id').write_text(parent, encoding='utf-8')
                self.assertIsNone(read()[1].get('meeting_source'))
                (child_folder / '.task_id').write_text(child, encoding='utf-8')
                (canonical / 'recording_owner').write_text('other', encoding='utf-8')
                self.assertTrue(all(n.get('meeting_source') is None for n in read()))


class NoteLibraryRouterTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "notes-router.db"
        self.media_dir = Path(self.temp_dir.name) / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = Path(self.temp_dir.name) / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )
        Base.metadata.create_all(self.engine)
        self.repository = NoteRepository()
        self.artifact_service = TaskArtifactService(output_dir=self.output_dir)

        self.app = FastAPI()
        self.app.include_router(note_library.router, prefix="/api")
        self.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(user_id="user-1")
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    @contextmanager
    def _session_scope(self):
        db = self.session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def test_meeting_save_retry_reuses_note_without_overwriting_content(self):
        with patch("app.services.note_repository.session_scope", self._session_scope):
            payload = NoteCreateRequest(title="会议", content="已编辑内容",
                                        task_id="meeting-task", source_type="meeting_recording")
            first = self.repository.create_note("user-1", payload)
            repeated = self.repository.create_note("user-1", payload.model_copy(update={"content": "旧草稿"}))
            other = self.repository.create_note("user-2", payload)
            self.assertEqual(first.id, repeated.id)
            self.assertEqual(repeated.content, "已编辑内容")
            self.assertNotEqual(first.id, other.id)
            self.assertEqual(len(self.repository.list_notes("user-1")), 1)

    def test_sqlite_note_responses_preserve_utc_timezone(self):
        with patch("app.services.note_repository.session_scope", self._session_scope):
            note = self.repository.create_note("user-1", NoteCreateRequest(title="会议"))
            response = self.client.get(f"/api/notes/{note.id}")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["created_at"].endswith("Z"))
            self.assertTrue(response.json()["updated_at"].endswith("Z"))

    def test_edit_versions_preserve_original_and_require_note_access(self):
        with patch("app.services.note_repository.session_scope", self._session_scope), patch("app.db.session_scope", self._session_scope):
            note = self.repository.create_note("user-1", NoteCreateRequest(title="会议", content="原始纪要", status="done"))
            self.assertEqual(self.client.patch(f"/api/notes/{note.id}", json={"content": "编辑后"}).status_code, 200)
            response = self.client.get(f"/api/notes/{note.id}/versions")
            self.assertEqual(response.status_code, 200)
            self.assertEqual([row["content"] for row in response.json()], ["原始纪要"])
            self.client.patch(f"/api/notes/{note.id}", json={"content": "编辑后"})
            self.assertEqual(len(self.client.get(f"/api/notes/{note.id}/versions").json()), 1)
            self.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(user_id="other")
            self.assertEqual(self.client.get(f"/api/notes/{note.id}/versions").status_code, 404)
            self.assertEqual(self.client.post(f"/api/notes/{note.id}/ask", json={"question": "会议决定是什么？"}).status_code, 404)

    def test_failed_processing_status_preserves_edited_draft(self):
        with patch("app.services.note_repository.session_scope", self._session_scope):
            note = self.repository.create_note("user-1", NoteCreateRequest(
                title="用户修改的标题", content="需要保留的正文", status="pending"))
            response = self.client.patch(f"/api/notes/{note.id}", json={"status": "failed"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "failed")
            self.assertEqual(response.json()["title"], "用户修改的标题")
            self.assertEqual(response.json()["content"], "需要保留的正文")

    def test_generation_origin_survives_cross_client_save_and_edit(self):
        from app.services.note_origin_service import record_origin
        folder = self.artifact_service.create_task_dir("origin-task")
        self.artifact_service.update_status(folder, "success", "ready")
        record_origin(folder, "mobile")
        record_origin(folder, "desktop")
        with patch("app.services.note_repository.session_scope", self._session_scope), patch.object(
            note_library, "_artifact_service", self.artifact_service
        ), patch("app.services.local_file_service.session_scope", self._session_scope), patch(
            "app.services.local_file_service.TaskArtifactService", return_value=self.artifact_service
        ):
            payload = {"title": "会议", "task_id": "origin-task", "source_type": "meeting_recording"}
            response = self.client.post("/api/notes", json=payload, headers={"X-VINote-Client": "desktop"})
            self.assertEqual(response.status_code, 201)
            note = response.json()
            self.assertEqual(note["generation_client"], "mobile")
            edited = self.client.patch(f"/api/notes/{note['id']}", json={"title": "新标题"})
            self.assertEqual(edited.json()["generation_client"], "mobile")
            legacy = self.client.post("/api/notes", json={"title": "旧纪要", "task_id": "missing"}, headers={"X-VINote-Client": "mobile"})
            self.assertIsNone(legacy.json()["generation_client"])
            self.assertEqual(self.client.delete(f"/api/notes/{note['id']}").status_code, 204)
            self.assertEqual(self.client.get(f"/api/notes/{note['id']}").status_code, 404)

    def test_get_note_media_streams_task_audio(self):
        media_file = self.media_dir / "episode.mp3"
        media_file.write_bytes(b"fake-audio")
        task_dir = self.artifact_service.create_task_dir("task-audio")
        self.artifact_service.update_status(task_dir, "success", "ready")
        self.artifact_service.save_audio_meta(
            task_dir,
            AudioDownloadResult(
                file_path=str(media_file),
                title="Episode",
                duration=42.0,
                video_id="episode-1",
                platform="podcast",
            ),
        )

        with patch("app.services.note_repository.session_scope", self._session_scope), patch.object(
            note_library,
            "_artifact_service",
            self.artifact_service,
        ):
            note = self.repository.create_note(
                "user-1",
                NoteCreateRequest(
                    title="Audio note",
                    content="body",
                    video_url="https://www.xiaoyuzhoufm.com/episode/demo",
                    task_id="task-audio",
                ),
            )

            response = self.client.get(f"/api/notes/{note.id}/media")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"fake-audio")
        self.assertEqual(response.headers["content-type"], "audio/mpeg")

    def test_get_note_media_prefers_staged_video_artifact(self):
        media_file = self.media_dir / "episode.mp3"
        media_file.write_bytes(b"fake-audio")
        task_dir = self.artifact_service.create_task_dir("task-video")
        self.artifact_service.update_status(task_dir, "success", "ready")
        staged_video = self.artifact_service.stage_media_file(task_dir, str(media_file), target_stem="source_video")
        staged_video = staged_video.with_suffix(".mp4")
        staged_video.write_bytes(b"fake-video")
        self.artifact_service.save_audio_meta(
            task_dir,
            AudioDownloadResult(
                file_path=str(media_file),
                title="Episode",
                duration=42.0,
                video_id="episode-1",
                platform="youtube",
            ),
        )

        with patch("app.services.note_repository.session_scope", self._session_scope), patch.object(
            note_library,
            "_artifact_service",
            self.artifact_service,
        ):
            note = self.repository.create_note(
                "user-1",
                NoteCreateRequest(
                    title="Video note",
                    content="body",
                    video_url="https://www.youtube.com/watch?v=demo",
                    task_id="task-video",
                ),
            )

            response = self.client.get(f"/api/notes/{note.id}/media")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"fake-video")
        self.assertEqual(response.headers["content-type"], "video/mp4")

    def test_get_note_media_prefers_declared_original_source(self):
        task_dir = self.artifact_service.create_task_dir("task-original")
        original = Path(self.temp_dir.name) / "meeting.webm"
        original.write_bytes(b"exact-original")
        self.artifact_service.stage_source_media(task_dir, str(original), media_kind="audio")
        normalized = task_dir / "media" / "source_audio.normalized.wav"
        normalized.write_bytes(b"normalized-copy")
        self.artifact_service.update_status(task_dir, "success", "ready")

        with patch("app.services.note_repository.session_scope", self._session_scope), patch.object(
            note_library,
            "_artifact_service",
            self.artifact_service,
        ):
            note = self.repository.create_note(
                "user-1",
                NoteCreateRequest(
                    title="Meeting",
                    content="body",
                    source_type="meeting_recording",
                    task_id="task-original",
                ),
            )
            response = self.client.get(f"/api/notes/{note.id}/media")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"exact-original")
        self.assertEqual(response.headers["content-type"], "audio/webm")

    def test_transcript_evidence_uses_local_artifact_and_overlays_speaker_aliases(self):
        task_dir = self.artifact_service.create_task_dir("task-transcript")
        self.artifact_service.update_status(task_dir, "success", "ready")
        self.artifact_service.save_transcript(
            task_dir,
            TranscriptResult(
                language="zh",
                full_text="原始内容",
                metadata={"asr_model": "sensevoice-small", "alignment": "timestamped"},
                segments=[
                    TranscriptSegment(
                        start=62.0,
                        end=72.0,
                        text="整理后的内容",
                        raw_text="原始内容",
                        cleaned_text="整理后的内容",
                        speaker_id="speaker_01",
                        speaker_label="Speaker 1",
                    )
                ],
            ),
        )

        with patch("app.services.note_repository.session_scope", self._session_scope), patch.object(
            note_library,
            "_artifact_service",
            self.artifact_service,
        ):
            note = self.repository.create_note(
                "user-1",
                NoteCreateRequest(title="Evidence", content="body", task_id="task-transcript"),
            )
            alias_response = self.client.patch(
                f"/api/notes/{note.id}/speakers",
                json={"aliases": {"speaker_01": "王老师"}},
            )
            response = self.client.get(f"/api/notes/{note.id}/transcript")

        self.assertEqual(alias_response.status_code, 200)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["language"], "zh")
        self.assertEqual(payload["aliases"], {"speaker_01": "王老师"})
        self.assertEqual(payload["metadata"]["asr_model"], "sensevoice-small")
        self.assertEqual(payload["segments"][0]["speaker_label"], "王老师")
        self.assertEqual(payload["segments"][0]["raw_text"], "原始内容")
        self.assertEqual(payload["segments"][0]["cleaned_text"], "整理后的内容")

    def test_transcript_evidence_returns_empty_shape_and_enforces_access(self):
        with patch("app.services.note_repository.session_scope", self._session_scope), patch.object(
            note_library,
            "_artifact_service",
            self.artifact_service,
        ):
            note = self.repository.create_note(
                "user-1",
                NoteCreateRequest(title="No transcript", content="body"),
            )
            empty_response = self.client.get(f"/api/notes/{note.id}/transcript")
            self.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(user_id="user-2")
            denied_response = self.client.get(f"/api/notes/{note.id}/transcript")

        self.assertEqual(empty_response.status_code, 200)
        self.assertEqual(
            empty_response.json(),
            {"language": None, "full_text": "", "segments": [], "aliases": {}, "metadata": {}},
        )
        self.assertEqual(denied_response.status_code, 404)

    def test_speaker_alias_validation_rejects_unsafe_identifiers(self):
        with patch("app.services.note_repository.session_scope", self._session_scope):
            note = self.repository.create_note(
                "user-1",
                NoteCreateRequest(title="Aliases", content="body"),
            )
            response = self.client.patch(
                f"/api/notes/{note.id}/speakers",
                json={"aliases": {"../speaker": "Unsafe"}},
            )

        self.assertEqual(response.status_code, 400)

    def test_get_note_media_returns_404_without_task_id(self):
        with patch("app.services.note_repository.session_scope", self._session_scope), patch.object(
            note_library,
            "_artifact_service",
            self.artifact_service,
        ):
            note = self.repository.create_note(
                "user-1",
                NoteCreateRequest(title="No media", content="body"),
            )

            response = self.client.get(f"/api/notes/{note.id}/media")

        self.assertEqual(response.status_code, 404)

    def test_team_member_can_access_team_note(self):
        self.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(user_id="user-2")

        with patch("app.services.note_repository.session_scope", self._session_scope):
            with self._session_scope() as db:
                team = TeamDB(id="team-1", name="Core", owner_id="user-1")
                db.add(team)
                db.add_all(
                    [
                        TeamMemberDB(team_id="team-1", user_id="user-1", role="owner"),
                        TeamMemberDB(team_id="team-1", user_id="user-2", role="member"),
                    ]
                )

            note = self.repository.create_note(
                "user-1",
                NoteCreateRequest(
                    title="Team note",
                    content="shared body",
                    scope="team",
                    team_id="team-1",
                ),
            )

            list_response = self.client.get("/api/notes?scope=team&team_id=team-1")
            self.assertEqual(list_response.status_code, 200)
            data = list_response.json()
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["id"], note.id)
            self.assertEqual(data[0]["scope"], "team")
            self.assertEqual(data[0]["team_name"], "Core")

            detail_response = self.client.get(f"/api/notes/{note.id}")
            self.assertEqual(detail_response.status_code, 200)
            self.assertEqual(detail_response.json()["id"], note.id)

    def test_non_member_cannot_create_or_open_team_note(self):
        self.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(user_id="user-2")

        with patch("app.services.note_repository.session_scope", self._session_scope):
            with self._session_scope() as db:
                db.add(TeamDB(id="team-1", name="Core", owner_id="user-1"))
                db.add(TeamMemberDB(team_id="team-1", user_id="user-1", role="owner"))

            create_response = self.client.post(
                "/api/notes",
                json={
                    "title": "Unauthorized team note",
                    "content": "body",
                    "scope": "team",
                    "team_id": "team-1",
                },
            )
            self.assertEqual(create_response.status_code, 400)
            self.assertEqual(create_response.json()["detail"], "Team not found or access denied")

            note = self.repository.create_note(
                "user-1",
                NoteCreateRequest(title="Private team note", content="body", scope="team", team_id="team-1"),
            )

            list_response = self.client.get("/api/notes?scope=team&team_id=team-1")
            self.assertEqual(list_response.status_code, 200)
            self.assertEqual(list_response.json(), [])

            detail_response = self.client.get(f"/api/notes/{note.id}")
            self.assertEqual(detail_response.status_code, 404)

    def test_personal_and_team_lists_are_isolated(self):
        with patch("app.services.note_repository.session_scope", self._session_scope):
            with self._session_scope() as db:
                db.add(TeamDB(id="team-1", name="Core", owner_id="user-1"))
                db.add(TeamMemberDB(team_id="team-1", user_id="user-1", role="owner"))

            personal_note = self.repository.create_note(
                "user-1",
                NoteCreateRequest(title="Personal note", content="personal body"),
            )
            team_note = self.repository.create_note(
                "user-1",
                NoteCreateRequest(title="Team note", content="team body", scope="team", team_id="team-1"),
            )

            personal_response = self.client.get("/api/notes?scope=personal")
            team_response = self.client.get("/api/notes?scope=team&team_id=team-1")

            self.assertEqual(personal_response.status_code, 200)
            self.assertEqual([item["id"] for item in personal_response.json()], [personal_note.id])
            self.assertEqual(team_response.status_code, 200)
            self.assertEqual([item["id"] for item in team_response.json()], [team_note.id])

    def test_team_member_can_update_and_delete_team_note(self):
        self.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(user_id="user-2")

        with patch("app.services.note_repository.session_scope", self._session_scope):
            with self._session_scope() as db:
                db.add(TeamDB(id="team-1", name="Core", owner_id="user-1"))
                db.add_all(
                    [
                        TeamMemberDB(team_id="team-1", user_id="user-1", role="owner"),
                        TeamMemberDB(team_id="team-1", user_id="user-2", role="member"),
                    ]
                )

            note = self.repository.create_note(
                "user-1",
                NoteCreateRequest(title="Team draft", content="before", scope="team", team_id="team-1"),
            )

            update_response = self.client.patch(
                f"/api/notes/{note.id}",
                json={"title": "Updated team note", "content": "after"},
            )
            self.assertEqual(update_response.status_code, 200)
            self.assertEqual(update_response.json()["title"], "Updated team note")
            self.assertEqual(update_response.json()["content"], "after")

            delete_response = self.client.delete(f"/api/notes/{note.id}")
            self.assertEqual(delete_response.status_code, 204)

            detail_response = self.client.get(f"/api/notes/{note.id}")
            self.assertEqual(detail_response.status_code, 404)

    def test_removed_member_loses_team_note_access(self):
        self.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(user_id="user-2")

        with patch("app.services.note_repository.session_scope", self._session_scope):
            with self._session_scope() as db:
                db.add(TeamDB(id="team-1", name="Core", owner_id="user-1"))
                db.add_all(
                    [
                        TeamMemberDB(id="member-1", team_id="team-1", user_id="user-1", role="owner"),
                        TeamMemberDB(id="member-2", team_id="team-1", user_id="user-2", role="member"),
                    ]
                )

            note = self.repository.create_note(
                "user-1",
                NoteCreateRequest(title="Shared note", content="body", scope="team", team_id="team-1"),
            )
            before_response = self.client.get(f"/api/notes/{note.id}")
            self.assertEqual(before_response.status_code, 200)

            with self._session_scope() as db:
                membership = db.get(TeamMemberDB, "member-2")
                db.delete(membership)

            after_response = self.client.get(f"/api/notes/{note.id}")
            self.assertEqual(after_response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
