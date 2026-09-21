from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

NoteScope = Literal["personal", "team"]


class WorkspaceSummary(BaseModel):
    scope: NoteScope
    team_id: str | None = None
    team_name: str | None = None


class NoteRecordResponse(BaseModel):
    id: str
    title: str
    content: str
    video_url: str | None = None
    source_type: str | None = None
    task_id: str | None = None
    status: str
    scope: NoteScope = "personal"
    team_id: str | None = None
    team_name: str | None = None
    created_at: datetime
    updated_at: datetime


class NoteCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = ""
    video_url: str | None = None
    source_type: str | None = None
    task_id: str | None = None
    status: str = "done"
    scope: NoteScope = "personal"
    team_id: str | None = None


class NoteUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = None
    status: str | None = None


class SpeakerAliasesUpdateRequest(BaseModel):
    aliases: dict[str, str] = Field(default_factory=dict)


class SpeakerAliasesResponse(BaseModel):
    aliases: dict[str, str]


class TranscriptEvidenceSegment(BaseModel):
    start: float
    end: float
    text: str
    raw_text: str | None = None
    cleaned_text: str | None = None
    speaker_id: str | None = None
    speaker_label: str | None = None


class TranscriptEvidenceResponse(BaseModel):
    language: str | None = None
    full_text: str = ""
    segments: list[TranscriptEvidenceSegment] = Field(default_factory=list)
    aliases: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)


class NoteShareRecord(BaseModel):
    note_id: str
    title: str
    share_enabled: bool
    share_token: str | None = None
    share_created_at: datetime | None = None


class NoteShareResponse(NoteShareRecord):
    share_url: str | None = None


class PublicSharedNoteResponse(BaseModel):
    title: str
    content: str
    video_url: str | None = None
    source_type: str | None = None
    created_at: datetime
    updated_at: datetime
    share_created_at: datetime | None = None
