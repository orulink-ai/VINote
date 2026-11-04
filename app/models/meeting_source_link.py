"""Explicit display-only associations; never task/media execution authority."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MeetingSourceLinkDB(Base):
    __tablename__ = 'meeting_source_links'
    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    note_id: Mapped[str] = mapped_column(String(36), ForeignKey('notes.id', ondelete='CASCADE'), primary_key=True)
    # Provenance only; this does not replace NoteDB.task_id.
    original_note_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_task_id: Mapped[str] = mapped_column(String(36))
    source_version: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
    confirmed_at: Mapped[float] = mapped_column(Float)


class ConfirmMeetingSourceLink(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    confirmed: Literal[True]
    canonical_task_id: str
    source_version: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    expected_revision: Annotated[int, Field(ge=0)] = 0

    @field_validator('confirmed', mode='before')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('请明确确认此稿对应的原始录制')
        return value

    @field_validator('canonical_task_id')
    @classmethod
    def canonical_uuid(cls, value):
        if str(UUID(value)) != value:
            raise ValueError('Canonical UUID required')
        return value


class MeetingDisplayDB(Base):
    """User labels, independent of immutable capture and canonical identity."""
    __tablename__ = 'meeting_display_metadata'
    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    title: Mapped[str] = mapped_column(String(180), default='')
    meeting_date: Mapped[str | None] = mapped_column(String(10), nullable=True)


class MeetingDisplayUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(default='', max_length=180)
    meeting_date: str | None = None

    @field_validator('title')
    @classmethod
    def clean_title(cls, value):
        return value.strip()

    @field_validator('meeting_date')
    @classmethod
    def calendar_date(cls, value):
        from datetime import date
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError('使用 YYYY-MM-DD 格式的会议日期')
        return value
