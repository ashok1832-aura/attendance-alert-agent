"""Azure Communication Services Email sender (managed identity, no connection strings)."""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from azure.communication.email import EmailClient
from azure.identity import DefaultAzureCredential

from src.config import get_settings

logger = logging.getLogger(__name__)

MAX_SUBJECT_CHARS = 200
MAX_BODY_CHARS = 20_000
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-']+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


class InvalidEmailRequest(ValueError):
    """The request was rejected before anything was sent."""


class DuplicateEmail(InvalidEmailRequest):
    """The same email was already sent to this recipient within the duplicate window."""


# Duplicate guard: an identical email (same recipient, subject and body) is sent at most once per
# window, even if a caller repeats the request (e.g. an agent framework replaying an approved call).
DUPLICATE_WINDOW_SECONDS = 600
_recent_sends: dict[str, float] = {}
_recent_lock = threading.Lock()


def _claim(key: str) -> bool:
    """Record key as sent now; False if it was already sent within the window."""
    now = time.monotonic()
    with _recent_lock:
        for old_key, sent_at in list(_recent_sends.items()):
            if now - sent_at > DUPLICATE_WINDOW_SECONDS:
                del _recent_sends[old_key]
        if key in _recent_sends:
            return False
        _recent_sends[key] = now
        return True


def _release(key: str) -> None:
    with _recent_lock:
        _recent_sends.pop(key, None)


class _Sender(Protocol):
    def begin_send(self, message: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class SendResult:
    message_id: str
    status: str


@lru_cache
def _client() -> _Sender:
    return EmailClient(get_settings().acs_endpoint, DefaultAzureCredential())


def validate(to: str, subject: str, body: str) -> str:
    """Return the normalised recipient, or raise InvalidEmailRequest."""
    to = to.strip()
    if not _EMAIL.match(to):
        raise InvalidEmailRequest(f"'{to}' is not a valid email address")
    allowed = get_settings().allowed_recipient_domains
    if allowed and to.rsplit("@", 1)[1].lower() not in allowed:
        raise InvalidEmailRequest(f"Recipient domain of '{to}' is not in the allowed list")
    if not subject.strip() or len(subject) > MAX_SUBJECT_CHARS:
        raise InvalidEmailRequest(f"Subject must be 1-{MAX_SUBJECT_CHARS} characters")
    if not body.strip() or len(body) > MAX_BODY_CHARS:
        raise InvalidEmailRequest(f"Body must be 1-{MAX_BODY_CHARS} characters")
    return to


def send(to: str, subject: str, body: str, client: _Sender | None = None) -> SendResult:
    """Validate and send one plain-text email; blocks until ACS accepts or rejects it."""
    recipient = validate(to, subject, body)
    key = hashlib.sha256("\n".join((recipient.lower(), subject.strip(), body)).encode()).hexdigest()
    if not _claim(key):
        logger.warning("duplicate email to %s refused (identical email sent in the last %ds)",
                       recipient, DUPLICATE_WINDOW_SECONDS)
        raise DuplicateEmail(f"duplicate: this exact email was already sent to {recipient} "
                             f"in the last {DUPLICATE_WINDOW_SECONDS // 60} minutes")
    message = {
        "senderAddress": get_settings().sender_address,
        "recipients": {"to": [{"address": recipient}]},
        "content": {"subject": subject.strip(), "plainText": body},
    }
    try:
        result = (client or _client()).begin_send(message).result()
    except Exception:
        _release(key)  # nothing was sent, so a retry must be allowed
        raise
    send_result = SendResult(message_id=str(result.get("id", "")), status=str(result.get("status", "")))
    logger.info("email to %s -> status=%s id=%s", recipient, send_result.status, send_result.message_id)
    return send_result
