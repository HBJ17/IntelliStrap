from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    app_env: str = "dev"
    database_url: str = "sqlite:///./smartband.db"
    dashboard_password: str = "change-me"
    session_secret: str = "change-me"
    device_provision_secret: str = "change-me"
    public_base_url: str = "http://localhost:8000"

    messaging_mode: Literal["simulator", "twilio_sandbox", "twilio_production"] = "simulator"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = "whatsapp:+14155238886"
    twilio_content_sid_owner: str = ""
    twilio_content_sid_shop: str = ""

    mqtt_enabled: bool = False
    mqtt_url: str = ""
    mqtt_username: str = ""
    mqtt_password: str = ""

    dev_hold_seconds: int | None = None
    scheduler_enabled: bool = True

    @field_validator("dev_hold_seconds", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        return None if v in ("", None) else v

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
