"""Application configuration loaded from environment variables and ``.env``."""

from pathlib import Path
import re

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSION_MAX_AGE = 8 * 3600


class Settings(BaseSettings):
    """Runtime settings shared by the API and Alembic."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: str
    allowed_origins: str
    session_secret_key: str
    session_cookie_name: str = "kglearn_session"
    environment: str = "production"

    @model_validator(mode="after")
    def validate_production_security(self):
        if self.environment.lower() != "development":
            origins = [item.strip() for item in self.allowed_origins.split(",")]
            if any(not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?", origin) for origin in origins):
                raise ValueError("Production requires exact HTTPS Origins without paths or wildcards")
            if len(self.session_secret_key) < 64:
                raise ValueError("Production SESSION_SECRET_KEY must have at least 64 characters")
        return self


settings = Settings()
