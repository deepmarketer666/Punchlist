"""Application configuration, read once from environment variables."""

from __future__ import annotations

import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta

APP_VERSION = "1.0.0"
log = logging.getLogger("punchlist.config")


def _parse_duration(value: str) -> timedelta:
    """Parses '30m', '12h', '7d' style durations."""
    match = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", value or "")
    if not match:
        raise ValueError(f"Invalid JWT_EXPIRES_IN value: {value!r} (use e.g. 12h or 7d)")
    amount, unit = int(match.group(1)), match.group(2)
    units = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
    return timedelta(**{units[unit]: amount})


@dataclass(frozen=True)
class DemoUser:
    name: str = "Demo User"
    email: str = "demo@punchlist.test"
    password: str = "demo1234"


@dataclass(frozen=True)
class Config:
    env: str
    jwt_secret: str
    jwt_expires: timedelta
    database_url: str
    database_ssl: bool
    seed_demo: bool
    demo_user: DemoUser = field(default_factory=DemoUser)
    version: str = APP_VERSION

    @property
    def is_prod(self) -> bool:
        return self.env == "production"

    @property
    def is_test(self) -> bool:
        return self.env == "test"

    @classmethod
    def from_env(cls, overrides: dict | None = None) -> "Config":
        env = {**os.environ, **(overrides or {})}
        app_env = env.get("APP_ENV", "development")

        jwt_secret = env.get("JWT_SECRET", "")
        if not jwt_secret:
            if app_env == "production":
                # A random secret would sign everyone out on every restart, so fail loudly.
                raise RuntimeError("JWT_SECRET must be set in production")
            jwt_secret = secrets.token_hex(32)
            log.warning("JWT_SECRET not set - using a random dev secret (sessions reset on restart)")

        return cls(
            env=app_env,
            jwt_secret=jwt_secret,
            jwt_expires=_parse_duration(env.get("JWT_EXPIRES_IN", "7d")),
            database_url=env.get("DATABASE_URL", ""),
            database_ssl=env.get("DATABASE_SSL", "false").lower() == "true",
            seed_demo=env.get("SEED_DEMO", "true").lower() != "false",
        )
