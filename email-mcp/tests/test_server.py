from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src import mailer
from src.config import get_settings
from src.server import CallerAllowlistMiddleware, send_email


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACS_ENDPOINT", "https://acs.example.communication.azure.com")
    monkeypatch.setenv("SENDER_ADDRESS", "DoNotReply@test.azurecomm.net")
    monkeypatch.delenv("ALLOWED_RECIPIENT_DOMAINS", raising=False)
    get_settings.cache_clear()
    mailer._recent_sends.clear()


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def begin_send(self, message: dict[str, Any]) -> Any:
        self.sent.append(message)
        return SimpleNamespace(result=lambda: {"id": "msg-1", "status": "Succeeded"})


def test_send_builds_acs_message() -> None:
    client = FakeClient()
    result = mailer.send(" student@gmail.com ", "Attendance", "Hello", client=client)
    assert result.status == "Succeeded"
    assert client.sent[0]["recipients"]["to"] == [{"address": "student@gmail.com"}]
    assert client.sent[0]["senderAddress"] == "DoNotReply@test.azurecomm.net"


@pytest.mark.parametrize(
    ("to", "subject", "body"),
    [("not-an-email", "s", "b"), ("a@b.com", "", "b"), ("a@b.com", "s", " "), ("a@b.com", "x" * 201, "b")],
)
def test_validate_rejects_bad_input(to: str, subject: str, body: str) -> None:
    with pytest.raises(mailer.InvalidEmailRequest):
        mailer.validate(to, subject, body)


def test_recipient_domain_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_RECIPIENT_DOMAINS", "college.edu")
    get_settings.cache_clear()
    with pytest.raises(mailer.InvalidEmailRequest):
        mailer.validate("x@gmail.com", "s", "b")
    assert mailer.validate("x@college.edu", "s", "b") == "x@college.edu"


async def test_tool_reports_validation_error_without_sending() -> None:
    assert (await send_email("bad", "s", "b")).startswith("NOT_SENT")


async def test_tool_reports_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(mailer, "_client", lambda: client)
    assert (await send_email("a@b.com", "s", "b")).startswith("SENT: to=a@b.com status=Succeeded")


def test_identical_email_is_sent_only_once() -> None:
    client = FakeClient()
    mailer.send("a@b.com", "Attendance", "Dear A", client=client)
    with pytest.raises(mailer.DuplicateEmail):
        mailer.send("A@B.com ", "Attendance", "Dear A", client=client)  # same email, different casing
    assert len(client.sent) == 1


def test_different_email_to_same_student_is_allowed() -> None:
    client = FakeClient()
    mailer.send("a@b.com", "Attendance", "Dear A", client=client)
    mailer.send("a@b.com", "Attendance", "Dear A, reminder", client=client)
    assert len(client.sent) == 2


def test_duplicate_window_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    client, now = FakeClient(), [1000.0]
    monkeypatch.setattr(mailer.time, "monotonic", lambda: now[0])
    mailer.send("a@b.com", "Attendance", "Dear A", client=client)
    now[0] += mailer.DUPLICATE_WINDOW_SECONDS + 1
    mailer.send("a@b.com", "Attendance", "Dear A", client=client)
    assert len(client.sent) == 2


def test_failed_send_can_be_retried() -> None:
    class FailingClient:
        def begin_send(self, message: dict[str, Any]) -> Any:
            raise RuntimeError("ACS unavailable")

    with pytest.raises(RuntimeError):
        mailer.send("a@b.com", "Attendance", "Dear A", client=FailingClient())
    client = FakeClient()
    mailer.send("a@b.com", "Attendance", "Dear A", client=client)
    assert len(client.sent) == 1


async def test_tool_reports_duplicate_as_not_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(mailer, "_client", lambda: client)
    assert (await send_email("a@b.com", "s", "b")).startswith("SENT")
    assert (await send_email("a@b.com", "s", "b")).startswith("NOT_SENT: duplicate")
    assert len(client.sent) == 1


def _app(allowed: frozenset[str]) -> TestClient:
    inner = Starlette(routes=[
        Route("/mcp", lambda r: PlainTextResponse("mcp")),
        Route("/healthz", lambda r: PlainTextResponse("ok")),
    ])
    return TestClient(CallerAllowlistMiddleware(inner, allowed))


def test_allowlist_blocks_unknown_and_missing_principal() -> None:
    client = _app(frozenset({"agent-oid"}))
    assert client.get("/mcp").status_code == 403
    assert client.get("/mcp", headers={"X-MS-CLIENT-PRINCIPAL-ID": "someone-else"}).status_code == 403
    assert client.get("/mcp", headers={"X-MS-CLIENT-PRINCIPAL-ID": "AGENT-OID"}).status_code == 200
    assert client.get("/healthz").status_code == 200


def test_empty_allowlist_allows_all() -> None:
    assert _app(frozenset()).get("/mcp").status_code == 200
