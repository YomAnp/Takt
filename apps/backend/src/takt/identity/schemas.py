from datetime import time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Profile(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    display_name: str
    telegram_id: int | None
    telegram_username: str | None
    role: Literal["member", "admin", "superadmin"]
    is_active: bool
    onboarded: bool = False
    end_time: time | None = None


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    init_data: str = Field(min_length=1, max_length=16384)


class LoginOutput(BaseModel):
    token: str
    profile: Profile


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=80)
    end_time: time

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Enter a name.")
        return value

    @field_validator("end_time")
    @classmethod
    def local_clock(cls, value: time) -> time:
        if value.tzinfo is not None or value.second or value.microsecond:
            raise ValueError("Use local hours and minutes.")
        return value


class AccessChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: bool | None = None
    role: Literal["member", "admin"] | None = None
