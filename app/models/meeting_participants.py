"""Device/task-scoped human attendance assertions; never delivery receipts."""
from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MeetingParticipantConfirmationDB(Base):
    __tablename__ = "meeting_participant_confirmations"

    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    # Protocol-2 rows use the verified canonical meeting ID. Legacy protocol-1
    # evidence hashes never match and are not automatically promoted.
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    binding_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    note_key: Mapped[str] = mapped_column(String(36))  # Confirmation provenance only.
    evidence_revision: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
    participants_json: Mapped[str] = mapped_column(Text)
    confirmed_at: Mapped[float] = mapped_column(Float)


class MeetingSpeakerConfirmationDB(Base):
    """Separate table so existing devices need no ALTER of attendance rows."""
    __tablename__ = "meeting_speaker_confirmations"
    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    binding_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    evidence_revision: Mapped[str] = mapped_column(String(64))
    matches_json: Mapped[str] = mapped_column(Text)
