"""Agent settings. Each one comes from the environment (.env locally, container environment
variables when hosted on Foundry), else the default below.

Foundry injects FOUNDRY_PROJECT_ENDPOINT into the hosted container itself; every other runtime
setting is passed in by src/agent_deploy.py (see Config.hosted_env)."""

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()  # no-op when there is no .env (e.g. in the hosted container)

_REQUIRED = ("foundry_project_endpoint", "search_endpoint", "sql_server", "email_mcp_url")


@dataclass(frozen=True)
class Config:
    name: str
    foundry_project_endpoint: str
    model: str
    search_endpoint: str
    search_index: str
    search_type: str  # simple | semantic
    search_top_k: int
    sql_server: str
    sql_database: str
    email_mcp_url: str
    email_mcp_token_scope: str  # empty = no token (local MCP server only)
    credential_type: str  # cli (local) | managed_identity (hosted) | default
    acr_name: str
    image_tag: str

    @classmethod
    def from_env(cls) -> "Config":
        def get(name: str, default: str = "") -> str:
            return (os.getenv(name) or default).strip()

        config = cls(
            name="attendance-alert-agent",
            foundry_project_endpoint=get("FOUNDRY_PROJECT_ENDPOINT"),
            model=get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-5.4"),
            search_endpoint=get("SEARCH_ENDPOINT"),
            search_index=get("SEARCH_INDEX_NAME", "college-rag"),
            search_type=get("SEARCH_TYPE", "semantic"),
            search_top_k=int(get("SEARCH_TOP_K", "5")),
            sql_server=get("SQL_SERVER"),
            sql_database=get("SQL_DATABASE", "attendance"),
            email_mcp_url=get("EMAIL_MCP_URL"),
            email_mcp_token_scope=get("EMAIL_MCP_TOKEN_SCOPE"),
            credential_type=get("AZURE_CREDENTIAL_TYPE", "default").lower(),
            acr_name=get("ACR_NAME"),
            image_tag=get("IMAGE_TAG", "latest"),
        )
        missing = [name for name in _REQUIRED if not getattr(config, name)]
        if missing:
            raise RuntimeError(f"Missing required settings: {missing}. Set them in .env (see .env.example).")
        return config

    def hosted_env(self) -> dict[str, str]:
        """Environment variables for the hosted container (FOUNDRY_* / AGENT_* are reserved by Foundry)."""
        return {
            "AZURE_CREDENTIAL_TYPE": "managed_identity",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": self.model,
            "SEARCH_ENDPOINT": self.search_endpoint,
            "SEARCH_INDEX_NAME": self.search_index,
            "SEARCH_TYPE": self.search_type,
            "SEARCH_TOP_K": str(self.search_top_k),
            "SQL_SERVER": self.sql_server,
            "SQL_DATABASE": self.sql_database,
            "EMAIL_MCP_URL": self.email_mcp_url,
            "EMAIL_MCP_TOKEN_SCOPE": self.email_mcp_token_scope,
        }


@lru_cache
def get_config() -> Config:
    return Config.from_env()
