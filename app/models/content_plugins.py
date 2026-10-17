"""Account-scoped plugin installation and durable, explicitly saved previews."""
from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class ContentPluginSettingDB(Base):
    __tablename__ = "content_plugin_settings"
    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    plugin_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ContentPluginRunDB(Base):
    __tablename__ = "content_plugin_runs"
    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    plugin_id: Mapped[str] = mapped_column(String(40))
    note_key: Mapped[str] = mapped_column(String(160))
    fingerprint: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[str] = mapped_column(Text)
    base_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="running")
    output: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    save_payload: Mapped[str] = mapped_column(Text, default="")
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[str] = mapped_column(String(40))
