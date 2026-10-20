"""
VINote configuration.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE_PATH = BASE_DIR / "data" / "vinote.db"


@dataclass
class Settings:
    feishu_app_id: str = os.getenv("FEISHU_APP_ID", "").strip()
    feishu_app_secret: str = os.getenv("FEISHU_APP_SECRET", "").strip()
    feishu_redirect_uri: str = os.getenv("FEISHU_REDIRECT_URI", "").strip()
    feishu_tenant_key: str = os.getenv("FEISHU_TENANT_KEY", "").strip()
    feishu_service_url: str = os.getenv("VINOTE_INTEGRATION_URL", "").rstrip("/")
    workspace_service_url: str = os.getenv("VINOTE_WORKSPACE_URL", "").rstrip("/")
    workspace_cloud_runtime: bool = os.getenv("VINOTE_WORKSPACE_CLOUD", "false").lower() == "true"
    content_cloud_runtime: bool = os.getenv("VINOTE_CONTENT_CLOUD", "false").lower() == "true"
    content_upload_max_bytes: int = int(os.getenv("VINOTE_CONTENT_UPLOAD_MAX_BYTES", "134217728"))
    workspace_storage_url: str = os.getenv("VINOTE_STORAGE_URL", os.getenv("VINOTE_SUPABASE_URL", "")).rstrip("/")
    workspace_storage_key: str = os.getenv("VINOTE_STORAGE_SERVICE_KEY", "")
    workspace_storage_bucket: str = os.getenv("VINOTE_STORAGE_BUCKET", "vinote-content")
    feishu_doc_base_url: str = os.getenv("FEISHU_DOC_BASE_URL", "").rstrip("/")
    feishu_scopes: str = os.getenv("FEISHU_SCOPES", "offline_access docx:document docs:permission.member:create docs:permission.member:auth docs:permission.setting:read docs:permission.setting:write_only drive:drive.metadata:readonly wiki:space:read wiki:node:read wiki:node:create im:chat:read docx:document.block:convert contact:user:search")
    meeting_review_model: str = os.getenv("MEETING_REVIEW_MODEL", "gpt-6-astra").strip()
    diarization_cluster_threshold: float = float(os.getenv("DIARIZATION_CLUSTER_THRESHOLD", "0.5"))
    # Tracing is required for desktop source/test/release runtimes only.
    langfuse_enabled: bool = True
    desktop_runtime: bool = os.getenv("VINOTE_DESKTOP_RUNTIME", "false").lower() == "true"
    feishu_transport: str = os.getenv("VINOTE_FEISHU_TRANSPORT", "cli").strip()
    langfuse_base_url: str = os.getenv("LANGFUSE_BASE_URL", "http://192.168.1.118:3000").rstrip("/")
    langfuse_public_key: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    langfuse_secret_key: str = os.getenv("LANGFUSE_SECRET_KEY", "")
    langfuse_environment: str = os.getenv("LANGFUSE_TRACING_ENVIRONMENT", "development")
    langfuse_release: str = os.getenv("LANGFUSE_RELEASE", "0.5.2")

    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8900"))
    cors_allow_origins: str = os.getenv(
        "CORS_ALLOW_ORIGINS",
        ",".join(
            [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:3100",
                "http://127.0.0.1:3100",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://tauri.localhost",
                "https://tauri.localhost",
                "tauri://localhost",
            ]
        ),
    )

    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    llm_provider: str = os.getenv("LLM_PROVIDER", "openai-compatible")

    diarization_model_dir: Path = Path(os.getenv("DIARIZATION_MODEL_DIR", str(BASE_DIR / "data" / "models" / "diarization")))

    transcriber_type: str = os.getenv("TRANSCRIBER_TYPE", "groq")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    whisper_model_size: str = os.getenv("WHISPER_MODEL_SIZE", "base")
    whisper_device: str = os.getenv("WHISPER_DEVICE", "cpu")
    faster_whisper_compute_type: str = os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8")
    sensevoice_base_url: str = os.getenv("SENSEVOICE_BASE_URL", "http://localhost:50000")
    sensevoice_language: str = os.getenv("SENSEVOICE_LANGUAGE", "auto")
    sensevoice_model_size: str = os.getenv("SENSEVOICE_MODEL_SIZE", "small")
    sensevoice_use_gpu: bool = os.getenv("SENSEVOICE_USE_GPU", "false").lower() == "true"
    transcription_chunking_enabled: bool = os.getenv("TRANSCRIPTION_CHUNKING_ENABLED", "true").lower() == "true"
    transcription_chunk_max_duration_seconds: int = int(os.getenv("TRANSCRIPTION_CHUNK_MAX_DURATION_SECONDS", "1200"))
    transcription_chunk_overlap_seconds: int = int(os.getenv("TRANSCRIPTION_CHUNK_OVERLAP_SECONDS", "120"))
    transcription_chunk_target_file_size_mb: int = int(os.getenv("TRANSCRIPTION_CHUNK_TARGET_FILE_SIZE_MB", "20"))
    transcription_chunk_min_core_seconds: int = int(os.getenv("TRANSCRIPTION_CHUNK_MIN_CORE_SECONDS", "300"))
    transcription_chunk_bitrate_kbps: int = int(os.getenv("TRANSCRIPTION_CHUNK_BITRATE_KBPS", "64"))
    summary_default_max_chars: int = int(os.getenv("SUMMARY_DEFAULT_MAX_CHARS", "18000"))
    summary_default_max_segments: int = int(os.getenv("SUMMARY_DEFAULT_MAX_SEGMENTS", "180"))
    summary_chunk_max_chars: int = int(os.getenv("SUMMARY_CHUNK_MAX_CHARS", "12000"))
    summary_chunk_max_segments: int = int(os.getenv("SUMMARY_CHUNK_MAX_SEGMENTS", "120"))
    summary_chunk_overlap_segments: int = int(os.getenv("SUMMARY_CHUNK_OVERLAP_SEGMENTS", "5"))
    ytdlp_request_sleep_seconds: float = float(os.getenv("YTDLP_REQUEST_SLEEP_SECONDS", "1"))
    ytdlp_download_sleep_seconds: float = float(os.getenv("YTDLP_DOWNLOAD_SLEEP_SECONDS", "3"))
    ytdlp_max_download_sleep_seconds: float = float(os.getenv("YTDLP_MAX_DOWNLOAD_SLEEP_SECONDS", "6"))

    data_dir: Path = BASE_DIR / os.getenv("DATA_DIR", "data")
    output_dir: Path = BASE_DIR / os.getenv("OUTPUT_DIR", "output")

    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}")
    app_jwt_secret: str = os.getenv("APP_JWT_SECRET", "change-me-to-a-long-random-secret")
    access_token_expire_seconds: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_SECONDS", "604800"))
    auth_cookie_name: str = os.getenv("AUTH_COOKIE_NAME", "vinote_session")
    auth_cookie_secure: bool = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"
    auth_cookie_samesite: str = os.getenv("AUTH_COOKIE_SAMESITE", "lax")
    auth_cookie_domain: str = os.getenv("AUTH_COOKIE_DOMAIN", "")
    share_base_url: str = os.getenv("SHARE_BASE_URL", "").strip()

    model_profile_encryption_key: str = os.getenv("MODEL_PROFILE_ENCRYPTION_KEY", "")
    vilab_server_url: str = os.getenv("VILAB_SERVER_URL", "").rstrip("/")
    vilab_api_key: str = os.getenv("VILAB_API_KEY", "")
    cloud_auth_url: str = os.getenv("VINOTE_SUPABASE_URL", "").rstrip("/")
    cloud_auth_public_key: str = os.getenv("VINOTE_SUPABASE_PUBLISHABLE_KEY", "")
    azure_openai_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

    def __post_init__(self):
        if self.content_cloud_runtime and not self.workspace_cloud_runtime:
            raise ValueError("Cloud content requires VINOTE_WORKSPACE_CLOUD=true")
        if not 1024 <= self.content_upload_max_bytes <= 512 * 1024 * 1024:
            raise ValueError("Cloud content upload limit must be between 1 KiB and 512 MiB")
        if self.workspace_cloud_runtime:
            from urllib.parse import urlsplit
            if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise ValueError("Cloud workspace requires PostgreSQL; SQLite fallback is forbidden")
            if not self.cloud_auth_url or not self.cloud_auth_public_key:
                raise ValueError("Cloud workspace requires Supabase authentication")
            if not self.workspace_storage_key or urlsplit(self.workspace_storage_url).scheme != "https":
                raise ValueError("Cloud workspace requires private HTTPS attachment storage")
            if self.workspace_service_url or self.feishu_service_url:
                raise ValueError("Cloud workspace must serve requests directly, not proxy to itself")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


settings = Settings()
