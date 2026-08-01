from pydantic_settings import BaseSettings, SettingsConfigDict
import logging

class Settings(BaseSettings):
    stac_fastapi_url: str = "http://localhost:8000"
    # Browser-facing TiTiler base URL (host port / Traefik path).
    tiler_url: str = "http://localhost:8002"
    # Server-side TiTiler base URL (Docker DNS). Falls back to tiler_url.
    tiler_internal_url: str | None = None
    # Public file-server prefix used in STAC asset hrefs.
    file_server_url: str | None = None
    # File-server URL reachable from TiTiler / dashboard containers.
    file_server_internal_url: str | None = None
    dashboard_debug: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

STAC_FASTAPI_URL = settings.stac_fastapi_url
TILER_URL = settings.tiler_url
TILER_INTERNAL_URL = settings.tiler_internal_url or settings.tiler_url
FILE_SERVER_URL = (settings.file_server_url or "").rstrip("/")
FILE_SERVER_INTERNAL_URL = (settings.file_server_internal_url or "").rstrip("/")
DASHBOARD_DEBUG = settings.dashboard_debug

logging.info("TILER URL: %s", TILER_URL)
logging.info("TILER_INTERNAL_URL: %s", TILER_INTERNAL_URL)
logging.info("FILE_SERVER_URL: %s", FILE_SERVER_URL or "(unset)")
logging.info("FILE_SERVER_INTERNAL_URL: %s", FILE_SERVER_INTERNAL_URL or "(unset)")
logging.info("STAC_FASTAPI_URL: %s", STAC_FASTAPI_URL)
