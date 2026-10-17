import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utc_now():
    return datetime.now(timezone.utc)


class FeishuApplicationDB(Base):
    __tablename__ = "feishu_applications"
    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    credentials: Mapped[str] = mapped_column(Text)


class SourceRequestDB(Base):
    """Durable source submission receipt, unique across workers per account."""
    __tablename__ = "source_request_receipts"

    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(16), default="reserved")
    receipt_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class FeishuConnectionDB(Base):
    __tablename__ = "feishu_connections"
    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    open_id: Mapped[str] = mapped_column(String(100), default="")
    name: Mapped[str] = mapped_column(String(200), default="")
    tokens: Mapped[str] = mapped_column(Text, default="")
    preferences: Mapped[str] = mapped_column(Text, default='{}')
    expired: Mapped[bool] = mapped_column(Boolean, default=False)


class NoteVersionDB(Base):
    __tablename__ = "note_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    note_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FeishuOAuthDB(Base):
    __tablename__ = "feishu_oauth_states"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128))
    expires: Mapped[str] = mapped_column(String(32))


class FeishuDeliveryDB(Base):
    __tablename__ = "feishu_deliveries"
    __table_args__ = (UniqueConstraint("owner", "note_key", "revision", name="uq_feishu_delivery"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner: Mapped[str] = mapped_column(String(128), index=True)
    note_key: Mapped[str] = mapped_column(String(160))
    revision: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    document_id: Mapped[str] = mapped_column(String(100), default="")
    document_url: Mapped[str] = mapped_column(String(500), default="")
    written_blocks: Mapped[str] = mapped_column(String(20), default="0")
    recipients: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    lease_until: Mapped[str] = mapped_column(String(32), default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UserDB(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class AuthLoginEventDB(Base):
    """成功登录来源；客户端自报信息，不用于鉴权。"""
    __tablename__ = "auth_login_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    client: Mapped[str] = mapped_column(String(16))
    platform: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class VILabPreferenceDB(Base):
    __tablename__ = "vilab_preferences"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), default="cloud")
    asr_model: Mapped[str] = mapped_column(String(200), default="")
    llm_model: Mapped[str] = mapped_column(String(200), default="")


class UserPreferenceDB(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    language: Mapped[str] = mapped_column(String(16), default="en")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class TeamDB(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class TeamMemberDB(Base):
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class NoteDB(Base):
    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, default="")
    video_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    generation_client: Mapped[str | None] = mapped_column(String(16), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="done")
    structured_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str] = mapped_column(String(16), default="personal")
    team_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    share_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    share_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ModelProfileDB(Base):
    __tablename__ = "model_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_model_profiles_user_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str] = mapped_column(String(500))
    model_name: Mapped[str] = mapped_column(String(200))
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CloudAccountDB(Base):
    __tablename__ = "cloud_accounts"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_cloud_identity"),)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    issuer: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(320))
    session_encrypted: Mapped[str] = mapped_column(Text)


class STTProfileDB(Base):
    __tablename__ = "stt_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_stt_profiles_user_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    device: Mapped[str | None] = mapped_column(String(32), nullable=True)
    compute_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    use_gpu: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
