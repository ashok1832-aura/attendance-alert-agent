"""Talk to the HOSTED agent in Foundry over the Responses API, handling email approvals.

    uv run python -m scripts.invoke_hosted "Which students are below the attendance requirement?"
    uv run python -m scripts.invoke_hosted "Email the students below the attendance requirement"
    uv run python -m scripts.invoke_hosted --approve none "Email ..."     # reject every email

--approve ask (default) prompts for each email; all / none decide without prompting.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

from src.config.config import get_config


def _decide(item: Any, mode: str) -> bool:
    args = json.loads(item.arguments or "{}")
    print(f"\n--- APPROVAL NEEDED: {item.name} ---")
    for key, value in args.items():
        print(f"{key}: {value}")
    if mode != "ask":
        print(f"[auto: {'approve' if mode == 'all' else 'reject'}]")
        return mode == "all"
    return input("Approve? [y/N] ").strip().lower() == "y"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("message")
    parser.add_argument("--approve", choices=("ask", "all", "none"), default="ask")
    args = parser.parse_args()

    cfg = get_config()
    project = AIProjectClient(endpoint=cfg.foundry_project_endpoint, credential=AzureCliCredential(),
                              allow_preview=True)
    client = project.get_openai_client(agent_name=cfg.name)

    response = client.responses.create(input=args.message)
    while True:
        approvals = [item for item in response.output if item.type == "mcp_approval_request"]
        if not approvals:
            break
        decisions = [{"type": "mcp_approval_response", "approval_request_id": item.id,
                      "approve": _decide(item, args.approve)} for item in approvals]
        response = client.responses.create(input=decisions, previous_response_id=response.id)
    print(f"\nAgent> {response.output_text}")


if __name__ == "__main__":
    main()
