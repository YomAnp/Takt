from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TAKT_", extra="ignore", hide_input_in_errors=True)

    time_zone: str = "Europe/Moscow"
    database_url: SecretStr = SecretStr("postgresql+psycopg://takt:takt_local@127.0.0.1:5432/takt")

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            if url.drivername != "postgresql+psycopg" or not url.database or not url.host:
                raise ValueError
        except (ValueError, ArgumentError) as exc:
            raise ValueError("Use a PostgreSQL URL with the psycopg driver.") from exc
        return value

    @field_validator("time_zone")
    @classmethod
    def valid_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use a valid IANA time zone.") from exc
        return value
