import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.db_models import TeamDB, TeamMemberDB
from app.models.note_library import NoteCreateRequest, PublicSharedNoteResponse
from app.services.note_repository import NoteRepository
from app.services.share_service import render_shared_note_html


class NoteShareRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "share-test.db"
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

    def tearDown(self):
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

    def test_enable_share_generates_reusable_token(self):
        with patch("app.services.note_repository.session_scope", self._session_scope):
            note = self.repository.create_note(
                "user-1",
                NoteCreateRequest(title="Shared note", content="# Heading"),
            )

            first_share = self.repository.enable_share("user-1", note.id)
            second_share = self.repository.enable_share("user-1", note.id)
            public_note = self.repository.get_shared_note(first_share.share_token)

            self.assertIsNotNone(first_share)
            self.assertTrue(first_share.share_enabled)
            self.assertIsNotNone(first_share.share_token)
            self.assertEqual(first_share.share_token, second_share.share_token)
            self.assertIsNotNone(public_note)
            self.assertEqual(public_note.title, "Shared note")

    def test_disable_share_revokes_public_access(self):
        with patch("app.services.note_repository.session_scope", self._session_scope):
            note = self.repository.create_note(
                "user-1",
                NoteCreateRequest(title="Private again", content="body"),
            )
            share = self.repository.enable_share("user-1", note.id)

            disabled = self.repository.disable_share("user-1", note.id)
            public_note = self.repository.get_shared_note(share.share_token)

            self.assertIsNotNone(disabled)
            self.assertFalse(disabled.share_enabled)
            self.assertIsNone(public_note)

    def test_team_member_can_share_team_note(self):
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
                NoteCreateRequest(title="Shared team note", content="body", scope="team", team_id="team-1"),
            )

            share = self.repository.enable_share("user-2", note.id)
            public_note = self.repository.get_shared_note(share.share_token)

            self.assertIsNotNone(share)
            self.assertTrue(share.share_enabled)
            self.assertIsNotNone(public_note)
            self.assertEqual(public_note.title, "Shared team note")


class ShareHtmlRenderingTest(unittest.TestCase):
    def test_render_shared_note_html_escapes_content(self):
        note = PublicSharedNoteResponse(
            title='A <Title>',
            content='# Heading\n\n- item\n\n```python\nprint(1)\n```\n\n<script>alert(1)</script>',
            video_url="https://www.bilibili.com/video/BV1xx411c7mD",
            source_type="video",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            share_created_at=datetime.now(timezone.utc),
        )

        page = render_shared_note_html(note)

        self.assertIn("VINote", page)
        self.assertIn("&lt;Title&gt;", page)
        self.assertIn("<h1>Heading</h1>", page)
        self.assertIn("<li>item</li>", page)
        self.assertIn("<pre>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("player.html", page)


if __name__ == "__main__":
    unittest.main()
