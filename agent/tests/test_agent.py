from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import mssql_python
import pytest

from src.agent.tools import email, regulations, students
from src.config.config import Config

REQUIRED_ENV = {
    "FOUNDRY_PROJECT_ENDPOINT": "https://foundry.example/api/projects/p",
    "SEARCH_ENDPOINT": "https://search.example",
    "SQL_SERVER": "sql.example",
    "EMAIL_MCP_URL": "https://mcp.example/mcp",
}
ALL_SETTINGS = (*REQUIRED_ENV, "AZURE_AI_MODEL_DEPLOYMENT_NAME", "SEARCH_INDEX_NAME", "SEARCH_TYPE", "SEARCH_TOP_K",
                "SQL_DATABASE", "EMAIL_MCP_TOKEN_SCOPE", "AZURE_CREDENTIAL_TYPE",
                "ACR_NAME", "IMAGE_TAG")


@pytest.fixture
def cfg(monkeypatch: pytest.MonkeyPatch) -> Config:
    for name in ALL_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    for name, value in REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("EMAIL_MCP_TOKEN_SCOPE", "api://x/.default")
    return Config.from_env()


# ---------------------------------------------------------------- config


def test_defaults_apply(cfg: Config) -> None:
    assert cfg.model == "gpt-5.4"
    assert (cfg.search_index, cfg.search_type, cfg.search_top_k) == ("college-rag", "semantic", 5)
    assert cfg.sql_database == "attendance"
    assert cfg.credential_type == "default"


def test_missing_required_setting_fails_fast(cfg: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SQL_SERVER")
    with pytest.raises(RuntimeError, match="sql_server"):
        Config.from_env()


def test_hosted_env_uses_managed_identity_and_no_reserved_names(cfg: Config) -> None:
    env = cfg.hosted_env()
    assert env["AZURE_CREDENTIAL_TYPE"] == "managed_identity"
    assert env["SQL_SERVER"] == "sql.example"
    assert not any(name.startswith(("FOUNDRY_", "AGENT_")) for name in env)


# ---------------------------------------------------------------- tools


class FakeCredential:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def get_token(self, scope: str) -> Any:
        self.scopes.append(scope)
        return type("Token", (), {"token": "tok"})()


@pytest.fixture
def cred(cfg: Config, monkeypatch: pytest.MonkeyPatch) -> FakeCredential:
    """Point every tool module at the test config and a fake credential."""
    credential = FakeCredential()
    for module in (regulations, students, email):
        monkeypatch.setattr(module, "get_config", lambda: cfg)
        monkeypatch.setattr(module, "get_credential", lambda: credential)
    return credential


class FakeConn:
    description = [("student_id",), ("attendance_pct",)]

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> FakeConn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> FakeConn:
        return self

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return [("22CS002", Decimal("60.00")), ("22CS001", Decimal("70.00"))]


def test_students_tool_runs_parameterised_query(cred: FakeCredential, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn()
    monkeypatch.setattr(students.mssql_python, "connect", lambda *a, **k: conn)
    tool = students.get_students_below_attendance
    assert tool.name == "get_students_below_attendance" and tool.approval_mode == "never_require"
    rows = json.loads(tool.func(threshold_pct=75, regulation="R22"))
    assert rows == [{"student_id": "22CS002", "attendance_pct": 60.0},
                    {"student_id": "22CS001", "attendance_pct": 70.0}]
    sql, params = conn.executed[0]
    assert "attendance_pct < ?" in sql and params == (75, "R22")


def test_students_tool_retries_while_database_wakes_up(cred: FakeCredential,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_connect(*args: Any, **kwargs: Any) -> FakeConn:
        calls.append(1)
        if len(calls) < 3:
            raise mssql_python.OperationalError("Database 'attendance' is not currently available", "")
        return FakeConn()

    monkeypatch.setattr(students.mssql_python, "connect", fake_connect)
    monkeypatch.setattr(students.time, "sleep", lambda _: None)
    rows = json.loads(students.get_students_below_attendance.func(threshold_pct=75, regulation="R22"))
    assert len(rows) == 2 and len(calls) == 3


def test_students_tool_does_not_retry_other_errors(cred: FakeCredential, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_connect(*args: Any, **kwargs: Any) -> FakeConn:
        raise mssql_python.OperationalError("Login failed", "")

    monkeypatch.setattr(students.mssql_python, "connect", fake_connect)
    with pytest.raises(mssql_python.OperationalError):
        students.get_students_below_attendance.func(threshold_pct=75, regulation="R22")


def test_regulations_tool_searches_index(cred: FakeCredential, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeSearchClient:
        def __init__(self, endpoint: str, index_name: str, credential: Any) -> None:
            captured.update(endpoint=endpoint, index_name=index_name, credential=credential)

        def search(self, **kwargs: Any) -> list[dict[str, Any]]:
            captured.update(kwargs)
            return [{"chunk": "Minimum 75 percent.", "title": "regs.pdf"}]

    monkeypatch.setattr(regulations, "SearchClient", FakeSearchClient)
    tool = regulations.search_regulations
    assert tool.name == "search_regulations" and tool.approval_mode == "never_require"
    assert tool.func(query="attendance") == "[regs.pdf]\nMinimum 75 percent."
    assert captured["index_name"] == "college-rag" and captured["credential"] is cred
    assert captured["search_text"] == "attendance" and captured["query_type"] == "semantic"


def test_regulations_tool_reports_no_results(cred: FakeCredential, monkeypatch: pytest.MonkeyPatch) -> None:
    class EmptySearchClient:
        def __init__(self, *args: Any) -> None:
            pass

        def search(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

    monkeypatch.setattr(regulations, "SearchClient", EmptySearchClient)
    assert regulations.search_regulations.func(query="canteen") == "No matching regulations found."


def test_email_tool_always_requires_approval_and_signs_requests(cred: FakeCredential) -> None:
    tool = email.email_tool()
    assert tool.approval_mode == "always_require"
    assert list(tool.allowed_tools) == ["send_email"]
    assert email.auth_header({}) == {"Authorization": "Bearer tok"}
    assert cred.scopes == ["api://x/.default"]
