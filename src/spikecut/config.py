from functools import lru_cache
from pathlib import Path

from pydantic import PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PostgresDsn
    redis_url: RedisDsn

    s3_endpoint_url: str
    s3_access_key: str
    s3_secret_key: SecretStr
    s3_bucket: str = "clips"

    buffer_dir: Path = Path("/buffer")
    buffer_retention_s: int = 300
    segment_duration_s: int = 2

    log_level: str = "INFO"

    ffmpeg_path: str = "ffmpeg"


@lru_cache
def get_settings() -> Settings:
    return Settings()
