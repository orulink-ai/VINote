"""Text-only shared workspace: media remains on the originating device."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def now():
    return datetime.now(timezone.utc)


class WorkspaceNoteDB(Base):
    __tablename__ = "workspace_notes"
    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(String(32), default="text")
    source_device: Mapped[str] = mapped_column(String(120), default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    transcript_json: Mapped[str] = mapped_column(Text, default="null")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkspaceVersionDB(Base):
    __tablename__ = "workspace_versions"
    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    note_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16), default="imported")
    model: Mapped[str] = mapped_column(String(200), default="")
    parent_id: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkspaceOperationDB(Base):
    __tablename__ = "workspace_operations"
    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    note_key: Mapped[str] = mapped_column(String(160))
    digest: Mapped[str] = mapped_column(String(64))
    # An acknowledgement stores the committed revision, not every past full body.
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkspaceEvidenceDB(Base):
    __tablename__ = "workspace_evidence"
    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    note_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    transcript_json: Mapped[str] = mapped_column(Text, default="null")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkspaceVersionEvidenceDB(Base):
    __tablename__ = "workspace_version_evidence"
    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    note_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    version_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    evidence_revision: Mapped[int] = mapped_column(Integer)


class WorkspaceGenerationDB(Base):
    __tablename__ = "workspace_generations"
    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    note_key: Mapped[str] = mapped_column(String(160))
    digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="running")
    output: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    base_revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SpeakerInterval(StrictPayload):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    speaker_id: str | None = Field(default=None, max_length=100)
    overlap: bool = False

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("结束时间不能小于开始时间")
        return self


class Segment(SpeakerInterval):
    text: str = Field(max_length=100000)
    speaker_label: str | None = Field(default=None, max_length=120)
    timestamp_estimated: bool = False


class SharedTranscript(StrictPayload):
    full_text: str = Field(default="", max_length=1000000)
    segments: list[Segment] = Field(default_factory=list, max_length=50000)
    aliases: dict[str, str] = Field(default_factory=dict, max_length=100)
    speaker_intervals: list[SpeakerInterval] = Field(default_factory=list, max_length=50000)


class MediaMetadata(StrictPayload):
    project: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = Field(default=None, max_length=30)
    source_created_at: datetime | None = None
    duration: float | None = Field(default=None, ge=0, le=604800)
    recording_started_at: str | None = Field(default=None, max_length=100)
    recording_ended_at: str | None = Field(default=None, max_length=100)
    media_id: str | None = Field(default=None, max_length=160)
    source_device_id: str | None = Field(default=None, max_length=160)
    default_version_id: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def normalize_classification(self):
        if self.project is not None:
            self.project = self.project.strip()
        if self.tags is not None:
            if any(len(tag) > 80 for tag in self.tags):
                raise ValueError("标签不能超过80字")
            self.tags = list(dict.fromkeys(tag.strip() for tag in self.tags if tag.strip()))
        return self


class SharedVersion(StrictPayload):
    id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=300000)
    created_at: datetime
    kind: Literal["generated", "edit", "imported"] = "imported"
    model: str = Field(default="", max_length=200)
    parent_id: str = Field(default="", max_length=160)


class Operation(StrictPayload):
    base_revision: int = Field(ge=0)
    operation_id: str = Field(min_length=1, max_length=160)


class PutNote(Operation):
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=300000)
    source_type: Literal["text", "meeting_recording", "meeting_video", "audio", "video", "file"] = "text"
    source_device: str = Field(default="", max_length=120)
    archived: bool = False
    transcript: SharedTranscript | None = None
    metadata: MediaMetadata = Field(default_factory=MediaMetadata)
    versions: list[SharedVersion] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def bounded(self):
        if not self.title.strip():
            raise ValueError("标题不能为空")
        if len(self.model_dump_json().encode("utf-8")) > 8 * 1024 * 1024:
            raise ValueError("本次同步内容过大，请分批同步历史版本")
        return self


class GenerateVersion(Operation):
    instructions: str = Field(default="", max_length=5000)
    template: Literal["minutes", "summary", "actions"] = "minutes"
    model: str | None = Field(default=None, max_length=200)


class AskQuestion(StrictPayload):
    question: str = Field(min_length=1, max_length=5000)
    version_id: str | None = Field(default=None, max_length=160)
