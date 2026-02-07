from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # Base directory for data volumes
    BASE_DIR: str = "."

    # Auth credentials
    LOGIN_ID: str = "admin"
    LOGIN_PASSWORD: str = "admin"

    # JWT settings
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 30

    # Brave Search API
    BRAVE_SEARCH_API_KEY: str = ""

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

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
    def logs_dir(self) -> Path:
        return Path(self.BASE_DIR) / "logs"


settings = Settings()
