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

    HOST: str = "0.0.0.0"
    PORT: int = 8000

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


settings = Settings()
