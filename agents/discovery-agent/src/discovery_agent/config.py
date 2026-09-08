from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    selenium_grid_url: str = "http://localhost:4444"
    screenshot_root: Path = Path("/data/screenshots")
    max_pages: int = 3
    lmnr_project_api_key: str = ""

    # Chatbot targets only: run headed (not --headless) and give a human a
    # grace pause right after the first page load to clear an anti-bot
    # challenge / log in via the Selenium Grid's noVNC viewer, before
    # scraping elements or running the challenge detector.
    chatbot_captcha_grace_seconds: float = 30.0
    # Used instead of chatbot_captcha_grace_seconds when a persisted session
    # (from a previous job against the same domain) was restored - usually
    # only a residual check remains, not a full login.
    chatbot_reauth_grace_seconds: float = 45.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
