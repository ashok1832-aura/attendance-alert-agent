"""Chat with the agent in-process (no server), approving or rejecting each email in the terminal.

    uv run python -m scripts.local_chat
    uv run python -m scripts.local_chat "Email all students below the attendance requirement"
"""

from __future__ import annotations

import asyncio
import json
import sys

from agent_framework import Message

from src.agent.builder import build_agent


def _ask_approval(request: object) -> bool:
    call = request.function_call  # type: ignore[attr-defined]
    args = call.arguments if isinstance(call.arguments, dict) else json.loads(call.arguments or "{}")
    print(f"\n--- APPROVAL NEEDED: {call.name} ---")
    for key, value in args.items():
        print(f"{key}: {value}")
    return input("Approve? [y/N] ").strip().lower() == "y"


async def chat(first_message: str | None) -> None:
    agent = build_agent()
    session = agent.create_session()
    async with agent:
        message: str | Message | None = first_message
        while True:
            if message is None:
                text = input("\nLecturer> ").strip()
                if text.lower() in ("", "exit", "quit"):
                    return
                message = text
            result = await agent.run(message, session=session)
            while result.user_input_requests:
                responses = [req.to_function_approval_response(_ask_approval(req))
                             for req in result.user_input_requests]
                result = await agent.run(Message(role="user", contents=responses), session=session)
            print(f"\nAgent> {result.text}")
            message = None


if __name__ == "__main__":
    asyncio.run(chat(" ".join(sys.argv[1:]) or None))
