from pydantic_settings import BaseSettings
from pathlib import Path


_JWT_PLACEHOLDER_SUBSTRINGS = (
    "change-me",
    "changeme",
    "replace-with",
    "placeholder",
    "your-secret",
    "paperflow-secret",
)
_JWT_MIN_LENGTH = 32


class Settings(BaseSettings):
    BASE_DIR: str = "."

    LOGIN_ID: str = "admin"
    LOGIN_PASSWORD: str = "admin"

    # JWT — JWT_SECRET_KEY MUST be set via env; placeholders / short values are rejected at startup
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 30

    # Cookie security — set to true when serving over HTTPS
    COOKIE_SECURE: bool = False

    BRAVE_SEARCH_API_KEY: str = ""

    # MCP server (opt-in: empty MCP_API_KEY → completely disabled)
    MCP_API_KEY: str = ""
    MCP_JOB_TTL_DAYS: int = 7
    MCP_PUBLIC_BASE_URL: str = ""        # required when MCP enabled, e.g. http://localhost:8090
    MCP_ALLOWED_ORIGINS: str = ""        # CSV. empty → derive. explicit "*" → permissive opt-out.
    MCP_REQUIRE_TRANSLATION: bool = True  # rev4: reconcile downgrades complete→error when _ko.md missing

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Live TTS sidecar (Chatterbox-Multilingual)
    TTS_SERVICE_URL: str = "http://paperflow-tts:8100"

    # HLS audio token config (Task 9 endpoints consume these)
    AUDIO_TOKEN_SECRET: str = ""        # 빈 값이면 JWT_SECRET_KEY 사용(아래 property)
    AUDIO_PTOKEN_TTL: int = 43200       # 12h
    AUDIO_TOKEN_TTL: int = 43200
    AUDIO_RESUME_GRACE: int = 3600
    AUDIO_REQUIRE_COMPLETE: bool = True  # 생성-먼저: 합성 완료 후에만 재생 mount(라이브 스트리밍 비활성)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def validate_runtime(self) -> None:
        """Fail fast on missing/weak JWT secret. Called from create_app()."""
        secret = self.JWT_SECRET_KEY.strip()
        if not secret:
            raise RuntimeError(
                "JWT_SECRET_KEY is empty. Set a strong random value via the env var "
                "(e.g. `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`)."
            )
        if len(secret) < _JWT_MIN_LENGTH:
            raise RuntimeError(
                f"JWT_SECRET_KEY is too short ({len(secret)} chars). "
                f"Minimum length is {_JWT_MIN_LENGTH}."
            )
        normalized = secret.lower()
        for needle in _JWT_PLACEHOLDER_SUBSTRINGS:
            if needle in normalized:
                raise RuntimeError(
                    f"JWT_SECRET_KEY looks like a placeholder (contains '{needle}'). "
                    "Rotate to a strong random value."
                )

    @property
    def outputs_dir(self) -> Path:
        return Path(self.BASE_DIR) / "outputs"

    @property
    def archives_dir(self) -> Path:
        return Path(self.BASE_DIR) / "archives"

    @property
    def newones_dir(self) -> Path:
        return Path(self.BASE_DIR) / "newones"

    @property
    def newones_meta_dir(self) -> Path:
        return self.newones_dir / ".meta"

    @property
    def logs_dir(self) -> Path:
        return Path(self.BASE_DIR) / "logs"

    @property
    def mcp_enabled(self) -> bool:
        """Opt-in: MCP server is mounted only when MCP_API_KEY is set (>= 32 chars)
        AND MCP_PUBLIC_BASE_URL is configured."""
        if not (self.MCP_API_KEY and len(self.MCP_API_KEY) >= 32):
            return False
        if not self.MCP_PUBLIC_BASE_URL:
            raise RuntimeError(
                "MCP_API_KEY is set but MCP_PUBLIC_BASE_URL is missing. "
                "Set MCP_PUBLIC_BASE_URL (e.g. http://localhost:8090) or clear MCP_API_KEY."
            )
        return True

    @property
    def audio_secret(self) -> str:
        return self.AUDIO_TOKEN_SECRET or self.JWT_SECRET_KEY

    @property
    def mcp_allowed_origins_set(self) -> set[str]:
        """DNS rebinding defense (MCP MUST).
        - explicit "*" → permissive opt-out
        - explicit CSV → exactly those
        - empty → derive MCP_PUBLIC_BASE_URL origin + localhost/127.0.0.1 (http/https)
        """
        from urllib.parse import urlparse

        raw = self.MCP_ALLOWED_ORIGINS.strip()
        if raw == "*":
            return {"*"}
        explicit = {o.strip() for o in raw.split(",") if o.strip()}
        if explicit:
            return explicit
        defaults: set[str] = set()
        if self.MCP_PUBLIC_BASE_URL:
            p = urlparse(self.MCP_PUBLIC_BASE_URL)
            if p.scheme and p.netloc:
                defaults.add(f"{p.scheme}://{p.netloc}")
        defaults.update({
            "http://localhost", "https://localhost",
            "http://127.0.0.1", "https://127.0.0.1",
        })
        return defaults


settings = Settings()
