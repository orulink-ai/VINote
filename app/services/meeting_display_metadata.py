"""Display-only title/date. Never rename files, tasks or rewrite capture evidence."""
from fastapi import HTTPException
from sqlalchemy import select
from app.models.meeting_source_link import MeetingDisplayDB, MeetingDisplayUpdate
from app.models.local_file import LocalFileDB
from app.services.meeting_source_link import MeetingSourceLinkService, _uuid


class MeetingDisplayService:
    def __init__(self, session_factory=None, artifacts=None):
        from app.db import session_scope
        self.sessions = session_factory or session_scope
        self.links = MeetingSourceLinkService(self.sessions, artifacts)

    @staticmethod
    def wire(row, key=None):
        return dict(source_key=key or row.source_key, title=row.title, meeting_date=row.meeting_date)

    def list(self, owner):
        with self.sessions() as db:
            rows = db.scalars(select(MeetingDisplayDB).where(MeetingDisplayDB.owner == owner)).all()
            values = {row.source_key: self.wire(row) for row in rows}
            # A file's accepted task is an alias, not a new user-visible meeting.
            # Preserve edits made before generation without changing either ID.
            files = db.scalars(select(LocalFileDB).where(LocalFileDB.owner == owner)).all()
            for file in files:
                prior = values.get('file:' + file.id)
                if prior and file.task_id:
                    values.setdefault('task:' + file.task_id, {**prior, 'source_key': 'task:' + file.task_id})
            return {'items': list(values.values())}

    def update(self, owner, kind, identifier, payload: MeetingDisplayUpdate):
        try:
            _uuid(identifier)
            if kind not in ('task', 'file'):
                raise ValueError()
            with self.sessions() as db:
                if kind == 'task':
                    self.links._metadata(owner, identifier, capture_only=True)
                else:
                    file = db.get(LocalFileDB, identifier)
                    if not file or file.owner != owner or file.purpose != 'meeting':
                        raise ValueError()
                key = kind + ':' + identifier
                row = db.get(MeetingDisplayDB, (owner, key))
                if row is None:
                    row = MeetingDisplayDB(owner=owner, source_key=key)
                    db.add(row)
                row.title = payload.title
                row.meeting_date = payload.meeting_date
                db.flush()
                return self.wire(row)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(404, '找不到此账号的会议原件') from None
