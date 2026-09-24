from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    api_key: str

    s3_endpoint_url: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str = "clips"

    buffer_dir: str = "/buffer"
    buffer_minutes: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
