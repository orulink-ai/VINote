from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


STTProviderType = Literal[
    "vliab-server",
    "groq",
    "whisper",
    "faster-whisper",
    "sensevoice",
    "sensevoice-local",
]

GROQ_STT_BASE_URL = "https://api.groq.com/openai/v1"
LOCAL_STT_PROVIDERS = {"whisper", "faster-whisper", "sensevoice-local"}


class STTProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider: STTProviderType
    model_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    base_url: Optional[str] = Field(default=None, min_length=1, max_length=500)
    api_key: Optional[str] = Field(default=None, min_length=1, max_length=500)
    language: Optional[str] = Field(default=None, min_length=1, max_length=50)
    device: Optional[str] = Field(default=None, min_length=1, max_length=32)
    compute_type: Optional[str] = Field(default=None, min_length=1, max_length=32)
    use_gpu: Optional[bool] = None
    is_default: bool = False
    is_active: bool = True


class STTProfileUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    provider: Optional[STTProviderType] = None
    model_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    base_url: Optional[str] = Field(default=None, min_length=1, max_length=500)
    api_key: Optional[str] = Field(default=None, min_length=1, max_length=500)
    language: Optional[str] = Field(default=None, min_length=1, max_length=50)
    device: Optional[str] = Field(default=None, min_length=1, max_length=32)
    compute_type: Optional[str] = Field(default=None, min_length=1, max_length=32)
    use_gpu: Optional[bool] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class STTProfileResponse(BaseModel):
    id: str
    name: str
    provider: STTProviderType
    model_name: Optional[str] = None
    base_url: Optional[str] = None
    api_key_hint: str = ""
    language: Optional[str] = None
    device: Optional[str] = None
    compute_type: Optional[str] = None
    use_gpu: Optional[bool] = None
    is_default: bool
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class LocalSTTSupportStatus(BaseModel):
    provider: str = "faster-whisper"
    installed: bool
    install_command: str
    message: str


class ResolvedSTTConfig(BaseModel):
    cloud_user_id: Optional[str] = None
    provider: STTProviderType
    model_name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    language: Optional[str] = None
    device: Optional[str] = None
    compute_type: Optional[str] = None
    use_gpu: Optional[bool] = None


class STTProfileRecord(BaseModel):
    id: str
    user_id: str
    name: str
    provider: STTProviderType
    model_name: Optional[str] = None
    base_url: Optional[str] = None
    api_key_encrypted: Optional[str] = None
    language: Optional[str] = None
    device: Optional[str] = None
    compute_type: Optional[str] = None
    use_gpu: Optional[bool] = None
    is_default: bool
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
