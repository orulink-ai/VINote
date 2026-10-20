"""Additive Wiki grouping records. Import before init_db; no legacy migration."""
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MeetingWikiContext(BaseModel):
    """Internal hook result, NEVER a client request or authority from a title.

    The hook must read owner-authorized task/note records and a real saved
    format/version. If known, recorded_at is the recording start with its known
    offset; absent recording time stays None, never generation time or mtime.
    """
    model_config = ConfigDict(extra='forbid', frozen=True)
    owner: Annotated[str, Field(strict=True, min_length=1, max_length=128)]
    task_id: str
    canonical_task_id: str
    source_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    recorded_at: datetime | None = None
    meeting_topic: Annotated[str, Field(strict=True, min_length=1, max_length=500)]
    summary_format: Annotated[str, Field(strict=True, min_length=1, max_length=100)]
    version_id: Annotated[str, Field(strict=True, min_length=1, max_length=160)]

    @field_validator('task_id', 'canonical_task_id')
    @classmethod
    def canonical_uuid(cls, value):
        import uuid
        if str(uuid.UUID(value)) != value:
            raise ValueError('Canonical task UUID required')
        return value

    @field_validator('recorded_at')
    @classmethod
    def recording_time(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError('Known recording time offset required')
        return value

    @field_validator('meeting_topic', 'summary_format', 'version_id')
    @classmethod
    def meaningful_label(cls, value, info):
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError('Explicit single-line metadata required')
        return value if info.field_name == 'meeting_topic' else value.strip()


class FeishuMeetingWikiContainerDB(Base):
    __tablename__ = 'feishu_meeting_wiki_containers'
    # Hash commits owner + canonical task + original hash + binding + root.
    scope_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), index=True)
    scope_json: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(500))
    state: Mapped[str] = mapped_column(String(16))
    lease_id: Mapped[str] = mapped_column(String(36))
    lease_until: Mapped[float] = mapped_column(Float)
    node_token: Mapped[str] = mapped_column(String(200), default='')
    document_id: Mapped[str] = mapped_column(String(200), default='')
    document_url: Mapped[str] = mapped_column(String(500), default='')
    error_code: Mapped[str] = mapped_column(String(64), default='')


class FeishuMeetingWikiChildDB(Base):
    """Immutable child association only; the existing service owns its writes."""
    __tablename__ = 'feishu_meeting_wiki_children'
    __table_args__ = (UniqueConstraint('scope_key', 'summary_format', 'ordinal',
                                     name='uq_feishu_meeting_wiki_format_version'),)
    delivery_id: Mapped[str] = mapped_column(String(36), ForeignKey('feishu_deliveries.id'), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(64), ForeignKey('feishu_meeting_wiki_containers.scope_key'), index=True)
    snapshot: Mapped[str] = mapped_column(Text)
    summary_format: Mapped[str] = mapped_column(String(100))
    ordinal: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
