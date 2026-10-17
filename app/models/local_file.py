"""Device-local originals, intentionally separate from the shared workspace."""
from datetime import datetime
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from app.models.workspace import now


class LocalFileDB(Base):
    __tablename__ = "local_files"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), index=True)
    filename: Mapped[str] = mapped_column(String(250))
    category: Mapped[str] = mapped_column(String(16))
    # Content ownership is independent of the file extension.
    purpose: Mapped[str] = mapped_column(String(16), default="unassigned")
    path: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
