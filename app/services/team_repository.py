from sqlalchemy import delete, select, update

from app.db import session_scope
from app.db_models import NoteDB, TeamDB, TeamMemberDB, UserDB
from app.models.team import TeamCreateRequest, TeamMemberCreateRequest, TeamMemberResponse, TeamSummaryResponse


def _normalize_email(email: str) -> str:
    return email.strip().lower()


class TeamRepository:
    @staticmethod
    def _is_team_admin(db, *, user_id: str, team: TeamDB) -> bool:
        if team.owner_id == user_id:
            return True

        membership = db.scalar(
            select(TeamMemberDB).where(TeamMemberDB.team_id == team.id, TeamMemberDB.user_id == user_id)
        )
        return bool(membership and membership.role in {"owner", "admin"})

    @staticmethod
    def _build_team_response(db, team: TeamDB, *, current_user_id: str) -> TeamSummaryResponse:
        member_rows = db.execute(
            select(TeamMemberDB, UserDB)
            .join(UserDB, UserDB.id == TeamMemberDB.user_id)
            .where(TeamMemberDB.team_id == team.id)
            .order_by(TeamMemberDB.joined_at.asc())
        ).all()

        members = [
            TeamMemberResponse(
                id=membership.id,
                user_id=membership.user_id,
                email=user.email,
                role=membership.role,
                joined_at=membership.joined_at,
            )
            for membership, user in member_rows
        ]
        current_member = next((member for member in members if member.user_id == current_user_id), None)
        current_user_role = current_member.role if current_member else "member"
        return TeamSummaryResponse(
            id=team.id,
            name=team.name,
            owner_id=team.owner_id,
            current_user_role=current_user_role,
            member_count=len(members),
            created_at=team.created_at,
            updated_at=team.updated_at,
            members=members,
        )

    def list_teams(self, user_id: str) -> list[TeamSummaryResponse]:
        with session_scope() as db:
            teams = db.scalars(
                select(TeamDB)
                .join(TeamMemberDB, TeamMemberDB.team_id == TeamDB.id)
                .where(TeamMemberDB.user_id == user_id)
                .order_by(TeamDB.created_at.asc())
            ).all()
            return [self._build_team_response(db, team, current_user_id=user_id) for team in teams]

    def get_team(self, user_id: str, team_id: str) -> TeamSummaryResponse | None:
        with session_scope() as db:
            team = db.scalar(
                select(TeamDB)
                .join(TeamMemberDB, TeamMemberDB.team_id == TeamDB.id)
                .where(TeamDB.id == team_id, TeamMemberDB.user_id == user_id)
            )
            if not team:
                return None
            return self._build_team_response(db, team, current_user_id=user_id)

    def create_team(self, user_id: str, payload: TeamCreateRequest) -> TeamSummaryResponse:
        with session_scope() as db:
            name = payload.name.strip()
            if not name:
                raise ValueError("Team name cannot be empty")

            team = TeamDB(name=name, owner_id=user_id)
            db.add(team)
            db.flush()
            db.add(TeamMemberDB(team_id=team.id, user_id=user_id, role="owner"))
            db.flush()
            return self._build_team_response(db, team, current_user_id=user_id)

    def add_member(self, requester_id: str, team_id: str, payload: TeamMemberCreateRequest) -> TeamSummaryResponse | None:
        with session_scope() as db:
            team = db.get(TeamDB, team_id)
            if not team or not self._is_team_admin(db, user_id=requester_id, team=team):
                return None

            user = db.scalar(select(UserDB).where(UserDB.email == _normalize_email(payload.email)))
            if not user:
                raise ValueError("User with that email does not exist")

            existing = db.scalar(
                select(TeamMemberDB).where(TeamMemberDB.team_id == team_id, TeamMemberDB.user_id == user.id)
            )
            if existing:
                raise ValueError("User is already a team member")

            db.add(TeamMemberDB(team_id=team_id, user_id=user.id, role=payload.role))
            db.flush()
            return self._build_team_response(db, team, current_user_id=requester_id)

    def remove_member(self, requester_id: str, team_id: str, member_id: str) -> TeamSummaryResponse | None:
        with session_scope() as db:
            team = db.get(TeamDB, team_id)
            if not team or not self._is_team_admin(db, user_id=requester_id, team=team):
                return None

            membership = db.scalar(
                select(TeamMemberDB).where(TeamMemberDB.id == member_id, TeamMemberDB.team_id == team_id)
            )
            if not membership:
                return None
            if membership.user_id == team.owner_id:
                raise ValueError("Team owner cannot be removed")

            db.delete(membership)
            db.flush()
            return self._build_team_response(db, team, current_user_id=requester_id)

    def delete_team(self, requester_id: str, team_id: str) -> bool:
        with session_scope() as db:
            team = db.get(TeamDB, team_id)
            if not team:
                return False
            if team.owner_id != requester_id:
                raise PermissionError("Only the team owner can delete the team")

            # Keep every member's work accessible after the shared space is removed.
            # Each note remains owned by its original creator and returns to that
            # creator's personal workspace.
            db.execute(
                update(NoteDB)
                .where(NoteDB.team_id == team_id)
                .values(scope="personal", team_id=None)
            )
            db.execute(delete(TeamMemberDB).where(TeamMemberDB.team_id == team_id))
            db.delete(team)
            db.flush()
            return True

    def get_accessible_team_ids(self, user_id: str) -> list[str]:
        with session_scope() as db:
            return db.scalars(
                select(TeamMemberDB.team_id).where(TeamMemberDB.user_id == user_id)
            ).all()

    def is_team_member(self, user_id: str, team_id: str) -> bool:
        with session_scope() as db:
            membership = db.scalar(
                select(TeamMemberDB.id).where(TeamMemberDB.user_id == user_id, TeamMemberDB.team_id == team_id)
            )
            return membership is not None
