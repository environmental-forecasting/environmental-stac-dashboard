from pydantic_settings import BaseSettings, SettingsConfigDict
import logging

class Settings(BaseSettings):
    stac_fastapi_url: str = "http://localhost/api"
    # Browser-facing TiTiler base URL. Used when tiler_internal_url is unset.
    tiler_url: str = "http://localhost/tiles"
    # Server-side TiTiler base URL (Docker DNS). Falls back to tiler_url.
    tiler_internal_url: str | None = None
    dashboard_debug: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

STAC_FASTAPI_URL = settings.stac_fastapi_url
TILER_INTERNAL_URL = settings.tiler_internal_url or settings.tiler_url
DASHBOARD_DEBUG = settings.dashboard_debug

logging.info("TILER_INTERNAL_URL: %s", TILER_INTERNAL_URL)
logging.info("STAC_FASTAPI_URL: %s", STAC_FASTAPI_URL)
