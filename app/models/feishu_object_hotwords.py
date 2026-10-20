"""Device-visible Feishu objects and explicit aliases; no provider credentials."""
import uuid

from sqlalchemy import Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FeishuObjectDB(Base):
    __tablename__ = "feishu_object_hotword_objects"

    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    binding_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    name: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[float] = mapped_column(Float)


class FeishuObjectAliasDB(Base):
    __tablename__ = "feishu_object_hotword_aliases"
    __table_args__ = (
        UniqueConstraint("owner", "binding_hash", "alias_key", name="uq_feishu_object_alias"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner: Mapped[str] = mapped_column(String(128), index=True)
    binding_hash: Mapped[str] = mapped_column(String(64))
    alias: Mapped[str] = mapped_column(String(50))
    alias_key: Mapped[str] = mapped_column(String(200))
    target_id: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[float] = mapped_column(Float)
