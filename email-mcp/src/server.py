"""Email MCP server (streamable HTTP at /mcp).

    uv run python -m src.server

Authentication is done in front of the app by Azure Container Apps built-in auth (Easy Auth),
which validates the caller's Entra token and injects ``X-MS-CLIENT-PRINCIPAL-ID``. This app then
allows only the object ids in ALLOWED_PRINCIPAL_IDS (the agent's identity).
"""

from __future__ import annotations

import logging
import os

import anyio
import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src import mailer
from src.config import get_settings

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logging.getLogger("azure").setLevel(logging.WARNING)
logger = logging.getLogger("email_mcp")

PRINCIPAL_HEADER = b"x-ms-client-principal-id"
PUBLIC_PATHS = frozenset({"/healthz"})

mcp = FastMCP("email", host="0.0.0.0", stateless_http=True, json_response=True)


@mcp.tool()
async def send_email(to: str, subject: str, body: str) -> str:
    """Send one plain-text email to a single recipient.

    Args:
        to: Recipient email address (exactly one).
        subject: Email subject line.
        body: Plain-text email body.
    """
    try:
        result = await anyio.to_thread.run_sync(mailer.send, to, subject, body)
    except mailer.InvalidEmailRequest as exc:
        return f"NOT_SENT: {exc}"
    except Exception:
        logger.exception("send_email failed for %s", to)
        return f"FAILED: the email service could not send to {to}. Do not retry automatically."
    return f"SENT: to={to} status={result.status} message_id={result.message_id}"


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


class CallerAllowlistMiddleware:
    """Reject callers whose Entra object id is not allow-listed (no-op when the list is empty)."""

    def __init__(self, app: ASGIApp, allowed: frozenset[str]) -> None:
        self.app = app
        self.allowed = allowed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.allowed or scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        principal = dict(scope["headers"]).get(PRINCIPAL_HEADER, b"").decode().lower()
        if principal not in self.allowed:
            logger.warning("rejected caller principal=%r path=%s", principal or None, scope["path"])
            await JSONResponse({"error": "forbidden"}, status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app() -> ASGIApp:
    settings = get_settings()
    if not settings.allowed_principal_ids:
        logger.warning("ALLOWED_PRINCIPAL_IDS is empty: caller check disabled (local development only)")
    return CallerAllowlistMiddleware(mcp.streamable_http_app(), settings.allowed_principal_ids)


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(), host="0.0.0.0", port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
