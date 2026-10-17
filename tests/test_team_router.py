import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.db_models import NoteDB, TeamDB, TeamMemberDB, UserDB
from app.models.auth import AuthenticatedUser
from app.routers import teams
from app.services.auth_service import get_current_user


class TeamRouterTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "teams-router.db"
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
        self.app = FastAPI()
        self.app.include_router(teams.router, prefix="/api")
        self.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            user_id="user-1",
            email="owner@example.com",
        )
        self.client = TestClient(self.app)

        with self._session_scope() as db:
            db.add_all(
                [
                    UserDB(id="user-1", email="owner@example.com", password_hash="pw"),
                    UserDB(id="user-2", email="member@example.com", password_hash="pw"),
                ]
            )

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

    def test_create_team_and_add_member(self):
        with patch("app.services.team_repository.session_scope", self._session_scope):
            create_response = self.client.post("/api/teams", json={"name": "Core team"})
            self.assertEqual(create_response.status_code, 201)
            team = create_response.json()
            self.assertEqual(team["name"], "Core team")
            self.assertEqual(team["member_count"], 1)
            self.assertEqual(team["members"][0]["role"], "owner")

            add_response = self.client.post(
                f"/api/teams/{team['id']}/members",
                json={"email": "member@example.com"},
            )
            self.assertEqual(add_response.status_code, 200)
            updated = add_response.json()
            self.assertEqual(updated["member_count"], 2)
            self.assertEqual(
                sorted(member["email"] for member in updated["members"]),
                ["member@example.com", "owner@example.com"],
            )

    def test_add_member_rejects_unknown_or_duplicate_email(self):
        with patch("app.services.team_repository.session_scope", self._session_scope):
            team = self.client.post("/api/teams", json={"name": "Core team"}).json()

            first_add = self.client.post(
                f"/api/teams/{team['id']}/members",
                json={"email": "member@example.com"},
            )
            self.assertEqual(first_add.status_code, 200)

            duplicate = self.client.post(
                f"/api/teams/{team['id']}/members",
                json={"email": "member@example.com"},
            )
            self.assertEqual(duplicate.status_code, 400)
            self.assertEqual(duplicate.json()["detail"], "User is already a team member")

            unknown = self.client.post(
                f"/api/teams/{team['id']}/members",
                json={"email": "missing@example.com"},
            )
            self.assertEqual(unknown.status_code, 400)
            self.assertEqual(unknown.json()["detail"], "User with that email does not exist")

    def test_remove_owner_is_rejected(self):
        with patch("app.services.team_repository.session_scope", self._session_scope):
            team = self.client.post("/api/teams", json={"name": "Core team"}).json()
            owner_member = team["members"][0]

            response = self.client.delete(f"/api/teams/{team['id']}/members/{owner_member['id']}")

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"], "Team owner cannot be removed")

    def test_non_admin_cannot_manage_members(self):
        with patch("app.services.team_repository.session_scope", self._session_scope):
            team = self.client.post("/api/teams", json={"name": "Core team"}).json()
            add_member = self.client.post(
                f"/api/teams/{team['id']}/members",
                json={"email": "member@example.com"},
            )
            self.assertEqual(add_member.status_code, 200)
            member_entry = next(
                member for member in add_member.json()["members"] if member["email"] == "member@example.com"
            )

            self.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
                user_id="user-2",
                email="member@example.com",
            )

            add_response = self.client.post(
                f"/api/teams/{team['id']}/members",
                json={"email": "owner@example.com"},
            )
            self.assertEqual(add_response.status_code, 404)

            remove_response = self.client.delete(
                f"/api/teams/{team['id']}/members/{member_entry['id']}"
            )
            self.assertEqual(remove_response.status_code, 404)

    def test_owner_can_delete_team_and_preserve_notes_as_personal(self):
        with patch("app.services.team_repository.session_scope", self._session_scope):
            team = self.client.post("/api/teams", json={"name": "Temporary team"}).json()
            with self._session_scope() as db:
                db.add(NoteDB(
                    id="note-1",
                    title="Shared note",
                    scope="team",
                    team_id=team["id"],
                    created_by="user-1",
                ))

            response = self.client.delete(f"/api/teams/{team['id']}")
            self.assertEqual(response.status_code, 204)

            with self._session_scope() as db:
                self.assertIsNone(db.get(TeamDB, team["id"]))
                self.assertEqual(
                    db.query(TeamMemberDB).filter(TeamMemberDB.team_id == team["id"]).count(),
                    0,
                )
                note = db.get(NoteDB, "note-1")
                self.assertEqual(note.scope, "personal")
                self.assertIsNone(note.team_id)

    def test_non_owner_cannot_delete_team(self):
        with patch("app.services.team_repository.session_scope", self._session_scope):
            team = self.client.post("/api/teams", json={"name": "Protected team"}).json()
            self.client.post(
                f"/api/teams/{team['id']}/members",
                json={"email": "member@example.com"},
            )
            self.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
                user_id="user-2",
                email="member@example.com",
            )

            response = self.client.delete(f"/api/teams/{team['id']}")
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["detail"], "Only the team owner can delete the team")


if __name__ == "__main__":
    unittest.main()
