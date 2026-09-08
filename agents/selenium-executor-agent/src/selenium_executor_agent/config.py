from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    selenium_grid_url: str = "http://localhost:4444"
    screenshot_root: Path = Path("/data/screenshots")
    element_wait_seconds: float = 5.0
    default_wait_ms: float = 500.0
    lmnr_project_api_key: str = ""

    # Chatbot scenarios only (detected from the scenario's own steps):
    # run headed (not --headless) so a human can solve an anti-bot challenge
    # via the Selenium Grid's noVNC viewer, after a grace pause right after
    # page load.
    chatbot_captcha_grace_seconds: float = 30.0
    # Used instead of chatbot_captcha_grace_seconds when session_cookies were
    # restored - still gives a residual JS challenge time to clear, but a
    # full manual login is normally not needed so it doesn't have to be as
    # long.
    chatbot_reauth_grace_seconds: float = 45.0
    response_timeout_ms: float = 60000.0
    response_poll_interval_ms: float = 1000.0
    # A model that "thinks" before streaming can sit quiet for a few seconds
    # mid-reply - 3 cycles at the old 500ms interval (1.5s) was mistaken for
    # "done" during that pause, truncating the captured response. 5 cycles at
    # 1s each (5s of genuine silence) is a safer bar for "actually finished".
    response_stable_cycles: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
