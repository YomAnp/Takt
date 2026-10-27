"""Verification of Telegram Mini App launch data."""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl


class InvalidTelegramData(ValueError):
    pass


@dataclass(frozen=True)
class TelegramIdentity:
    id: int
    name: str
    username: str | None


def verify_init_data(raw: str, token: str, now: datetime) -> TelegramIdentity:
    try:
        if not raw or len(raw) > 16384:
            raise ValueError
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=40)
        values = dict(pairs)
        if len(values) != len(pairs):
            raise ValueError
        signature = values.pop("hash")
        secret = hmac.digest(b"WebAppData", token.encode(), "sha256")
        expected = hmac.new(
            secret,
            "\n".join(f"{key}={values[key]}" for key in sorted(values)).encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        age = now.timestamp() - int(values["auth_date"])
        if not -30 <= age <= 300:
            raise ValueError
        user = json.loads(values["user"])
        identifier = user["id"]
        if type(identifier) is not int or not 0 < identifier < 2**52 or user.get("is_bot", False):
            raise ValueError
        first = user["first_name"]
        last = user.get("last_name", "")
        username = user.get("username")
        if not isinstance(first, str) or not isinstance(last, str):
            raise ValueError
        if username is not None and not isinstance(username, str):
            raise ValueError
        name = " ".join((first + " " + last).split())[:80] or "Сотрудник"
        return TelegramIdentity(identifier, name, username)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        raise InvalidTelegramData("Invalid or expired Telegram launch data.") from exc
