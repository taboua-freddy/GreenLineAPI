from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GreenLine ETA API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite+aiosqlite:///./greenline.db"
    google_maps_api_key: str | None = None
    google_geocoding_api_key: str | None = None
    google_application_credentials: str | None = None
    hiboo_api_base_url: str = "https://api.hiboo.io"
    hiboo_api_name: str | None = None
    hiboo_api_key: str | None = None
    api_admin_token: str | None = None
    api_daily_limit_default: int = Field(default=1000, ge=1)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Retourne les paramètres chargés depuis l’environnement, en les mettant en cache."""
    return Settings()
