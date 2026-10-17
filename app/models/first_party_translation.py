"""First-party translation protocol manifest and private execution receipts."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Boolean, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ORIGIN = "https://supabase-vinote.orulink.ai/vinote-api"
ENDPOINT = ORIGIN + "/api/mcp-first-party/translation"
AUTH_TYPE = "vinote-session"
PROVIDER_ID = "vinote-cloud-translation"
PROVIDER_NAME = "VINote 云翻译 · 第一方 MCP"
TOOL_NAME = "vinote_translate_text"
EXECUTION_SECONDS = 90
BRIDGE_SECONDS = 120
TOOL = {
    "name": TOOL_NAME,
    "description": "Translate explicitly supplied text with the VINote cloud model service. Preview before saving.",
    "inputSchema": {
        "type": "object", "additionalProperties": False,
        "required": ["text", "target_language"],
        "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 60000},
                       "target_language": {"type": "string", "enum": ["zh", "en"]},
                       "model": {"type": "string", "minLength": 1, "maxLength": 200,
                                 "pattern": "^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$",
                                 "description": "Explicit available VINote cloud LLM ID. Omit only to follow a validated service default."}},
    },
    "annotations": {"destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
}


class TranslationArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=60000)
    target_language: Literal["zh", "en"]
    model: str = Field(default="", min_length=1, max_length=200,
                       pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$")

    @model_validator(mode="after")
    def nonblank(self):
        if not self.text.strip():
            raise ValueError("Text must not be blank")
        return self


class ProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FirstPartyTranslationDB(Base):
    __tablename__ = "mcp_first_party_translation_receipts"
    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    target_language: Mapped[str] = mapped_column(String(2))
    model: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20))
    dispatched: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_until: Mapped[float] = mapped_column(Float)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
