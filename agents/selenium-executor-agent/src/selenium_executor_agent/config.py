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


@lru_cache
def get_settings() -> Settings:
    return Settings()
