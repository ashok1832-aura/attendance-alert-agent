"""Container entry point — serves the agent on the Foundry Responses protocol (port 8088).

    uv run python -m src.main

Tool approvals (send_email) are emitted as approval requests and persisted by the hosting layer's
Foundry-backed approval store, so the run resumes when the lecturer approves or rejects.
"""

from __future__ import annotations

from agent_framework_foundry_hosting import ResponsesHostServer

from src.agent.builder import build_agent
from src.utils.log_helper import get_logger

logger = get_logger(__name__)


def main() -> None:
    try:
        agent = build_agent()
    except Exception:
        logger.exception("Failed to build agent")
        raise
    logger.info("Starting ResponsesHostServer on port 8088")
    ResponsesHostServer(agent).run()


if __name__ == "__main__":
    main()
