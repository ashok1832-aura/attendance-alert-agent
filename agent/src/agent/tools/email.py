"""Tool 3: send emails through the email MCP server (the lecturer must approve each one).

Unlike the other two tools this is not a @tool function: it is a connection to an MCP server,
and the agent can use the tools that server offers (here only send_email).
"""

from agent_framework import MCPStreamableHTTPTool

from src.agent.credential import get_credential
from src.config.config import get_config


def auth_header(_):
    # Sign every request with the agent's identity, so only this agent can send email.
    scope = get_config().email_mcp_token_scope
    if not scope:
        return {}
    return {"Authorization": f"Bearer {get_credential().get_token(scope).token}"}


def email_tool() -> MCPStreamableHTTPTool:
    return MCPStreamableHTTPTool(
        name="email",
        url=get_config().email_mcp_url,
        approval_mode="always_require",  # pause: Approve / Reject before every email
        allowed_tools=["send_email"],
        header_provider=auth_header,
    )
