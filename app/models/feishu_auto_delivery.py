"""Device-only opt-in and durable saved-minutes handoff, without media or tokens."""
import uuid

from sqlalchemy import Boolean, Float, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FeishuDevicePolicyDB(Base):
    __tablename__ = "feishu_device_policies"
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(36), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    integration_origin: Mapped[str] = mapped_column(String(2048), default="")
    cloud_owner: Mapped[str] = mapped_column(String(128), default="")


class FeishuMeetingSaveDB(Base):
    """First-save qualification, not an editable status or historical scan."""
    __tablename__ = "feishu_meeting_saves"
    note_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36))
    policy_id: Mapped[str] = mapped_column(String(36), default="")
    completed: Mapped[bool] = mapped_column(Boolean, default=False)


class FeishuAutoOutboxDB(Base):
    __tablename__ = "feishu_auto_outbox"
    __table_args__ = (UniqueConstraint("user_id", "note_id", name="uq_feishu_auto_note"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    note_id: Mapped[str] = mapped_column(String(36))
    policy_id: Mapped[str] = mapped_column(String(36))
    integration_origin: Mapped[str] = mapped_column(String(2048))
    cloud_owner: Mapped[str] = mapped_column(String(128))
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    job_id: Mapped[str] = mapped_column(String(36), default="")
    error: Mapped[str] = mapped_column(String(500), default="")
    lease_until: Mapped[float] = mapped_column(Float, default=0)
