"""Remote MCP storage and the shared desktop/mobile request contract.

Import this module before Base.metadata.create_all during application startup.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy import Boolean, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MCPConnectionDB(Base):
    __tablename__ = "mcp_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(Text)
    auth_type: Mapped[str] = mapped_column(String(16))
    credential: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="unverified")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools_json: Mapped[str] = mapped_column(Text, default="[]")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    discovered_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class MCPRunDB(Base):
    __tablename__ = "mcp_runs"
    __table_args__ = (UniqueConstraint("owner", "request_id", name="uq_mcp_owner_request"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), index=True)
    connection_id: Mapped[str] = mapped_column(String(36), index=True)
    request_id: Mapped[str] = mapped_column(String(128))
    tool_name: Mapped[str] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(64))
    connection_revision: Mapped[int] = mapped_column(Integer)
    definition_hash: Mapped[str] = mapped_column(String(64))
    arguments_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    confirmation_token: Mapped[str] = mapped_column(String(64))
    confirmation_expires: Mapped[float] = mapped_column(Float)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    active_owner: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class ConnectionCreate(RequestModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)
    authType: Literal["none", "token"] = "none"
    token: SecretStr | None = Field(default=None, max_length=8192)
    enabled: bool = True


class ConnectionPatch(RequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    authType: Literal["none", "token"] | None = None
    token: SecretStr | None = Field(default=None, max_length=8192)
    enabled: bool | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set or any(getattr(self, k) is None for k in self.model_fields_set):
            raise ValueError("Provide non-null fields to update")
        return self


class ToolPatch(RequestModel):
    name: str = Field(min_length=1, max_length=200)
    enabled: bool


class InvokeRequest(RequestModel):
    requestId: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    toolName: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False
    confirmationToken: str | None = Field(default=None, max_length=64)


def request_body(payload: RequestModel, *, exclude_unset: bool = False) -> dict:
    """SecretStr masks repr, but the authenticated proxy must receive its value."""
    body = payload.model_dump(exclude_unset=exclude_unset)
    if isinstance(body.get("token"), SecretStr):
        body["token"] = body["token"].get_secret_value()
    return body
