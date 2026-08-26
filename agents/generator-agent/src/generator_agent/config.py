from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    ollama_host: str = "http://localhost:11434"
    llm_model: str = "qwen2.5:3b"
    max_scenarios: int = 3
    generation_timeout: float = 90.0
    lmnr_project_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
