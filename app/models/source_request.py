"""Validated identities for source submissions; no source bytes are persisted."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["url", "upload", "retained_file"]
    url: str | None = Field(default=None, min_length=1, max_length=8192)
    file_type: str | None = Field(default=None, min_length=1, max_length=120)
    filename: str | None = Field(default=None, min_length=1, max_length=512)
    size: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    retained_file_id: str | None = Field(default=None, min_length=1, max_length=160)
    retained_file_version: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def require_identity(self):
        if self.kind == "url":
            if not self.url or any(value is not None for value in (
                self.file_type, self.filename, self.size, self.sha256,
                self.retained_file_id, self.retained_file_version,
            )):
                raise ValueError("URL submissions require only a URL source identity")
        elif self.kind == "upload":
            if (self.url or self.retained_file_id or self.retained_file_version or
                    not self.file_type or self.size is None or not self.sha256):
                raise ValueError("Uploads require server-verified file type, size and SHA-256")
        elif (self.url or not self.retained_file_id or not self.retained_file_version):
            raise ValueError("Retained files require an owner-verified ID and immutable version")
        return self


class SourceSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: SourceInput
    # Supply all normalized effective generation options, not client-only fields.
    options: dict[str, JsonValue] = Field(default_factory=dict)


class SourceRequestReceipt(BaseModel):
    operation_id: str
    task_id: str
    state: Literal["reserved", "accepted"]
    status: str
    source_type: str | None = None
    created: bool = False
