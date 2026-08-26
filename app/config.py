from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    db_url: str = "postgresql://qa:qa@localhost:5433/qa_swarm"
    ollama_host: str = "http://localhost:11434"
    selenium_grid_url: str = "http://localhost:4445"
    vision_model: str = "llava:7b"
    llm_model: str = "qwen2.5:3b"
    max_concurrency: int = 2
    lmnr_project_api_key: str = ""
    screenshot_root: str = "/data/screenshots"
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    discovery_agent_url: str = "http://localhost:8001/run"
    vision_agent_url: str = "http://localhost:8002/run"
    generator_agent_url: str = "http://localhost:8003/run"
    validator_agent_url: str = "http://localhost:8004/run"
    selenium_executor_agent_url: str = "http://localhost:8005/run"
    llm_judge_agent_url: str = "http://localhost:8006/run"


@lru_cache
def get_settings() -> Settings:
    return Settings()
