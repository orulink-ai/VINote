"""Execution fencing for workspace generations without altering existing tables.

Import before Base.metadata.create_all. All workers must run the fenced service.
"""
from sqlalchemy import Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class WorkspaceGenerationClaimDB(Base):
    __tablename__ = "workspace_generation_claims"

    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    note_key: Mapped[str] = mapped_column(String(160))
    digest: Mapped[str] = mapped_column(String(64))
    execution_token: Mapped[str] = mapped_column(String(64), default="")
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    # Immutable once set. A retry publishes the exact same validated PutNote,
    # including version timestamps; raw model/network credentials never enter it.
    publication_json: Mapped[str] = mapped_column(Text, default="")
