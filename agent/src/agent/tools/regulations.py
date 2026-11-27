"""Tool 1: search the college regulations (Azure AI Search)."""

from typing import Annotated

from agent_framework import tool
from azure.search.documents import SearchClient
from pydantic import Field

from src.agent.credential import get_credential
from src.config.config import get_config


@tool(approval_mode="never_require")
def search_regulations(
    query: Annotated[str, Field(description="What to look up, e.g. 'minimum attendance requirement'.")],
) -> str:
    """Search the college regulations. Call this first to find the attendance rules
    (minimum percentage, condonation band, detention) before looking up any students."""
    cfg = get_config()
    client = SearchClient(cfg.search_endpoint, cfg.search_index, get_credential())
    results = client.search(search_text=query, top=cfg.search_top_k, query_type=cfg.search_type)
    chunks = [f"[{doc.get('title')}]\n{doc.get('chunk')}" for doc in results]
    return "\n\n".join(chunks) or "No matching regulations found."
