from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    ocr_lang: str = "fra+eng"
    ocr_psm: int = 11
    ocr_confidence_threshold: float = 40.0
    ocr_upscale_factor: int = 2

    ollama_host: str = "http://localhost:11434"
    vlm_model: str = "moondream"
    vlm_iou_threshold: float = 0.3
    vlm_max_crop_calls: int = 5
    vlm_timeout: float = 90.0
    lmnr_project_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
