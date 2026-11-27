"""Settings for the email MCP server — the only module that reads the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _csv(value: str | None) -> frozenset[str]:
    return frozenset(item.strip().lower() for item in (value or "").split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    acs_endpoint: str  # https://<acs>.communication.azure.com
    sender_address: str  # DoNotReply@<domain>.azurecomm.net
    # Entra object ids allowed to call the server (checked against the header Easy Auth injects).
    # Empty = no caller check, for local development only.
    allowed_principal_ids: frozenset[str]
    # Optional recipient-domain allowlist, e.g. "college.edu,gmail.com". Empty = any domain.
    allowed_recipient_domains: frozenset[str]
    port: int


@lru_cache
def get_settings() -> Settings:
    missing = [name for name in ("ACS_ENDPOINT", "SENDER_ADDRESS") if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variable(s): {missing}")
    return Settings(
        acs_endpoint=os.environ["ACS_ENDPOINT"].rstrip("/"),
        sender_address=os.environ["SENDER_ADDRESS"],
        allowed_principal_ids=_csv(os.environ.get("ALLOWED_PRINCIPAL_IDS")),
        allowed_recipient_domains=_csv(os.environ.get("ALLOWED_RECIPIENT_DOMAINS")),
        port=int(os.environ.get("PORT", "8080")),
    )
