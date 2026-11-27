"""One Azure credential per process, chosen by AZURE_CREDENTIAL_TYPE.

| AZURE_CREDENTIAL_TYPE | Class                     | Where                              |
|-----------------------|---------------------------|------------------------------------|
| cli                   | AzureCliCredential        | local development (`az login`)     |
| managed_identity      | ManagedIdentityCredential | Foundry hosted agent               |
| default (or unset)    | DefaultAzureCredential    | anything else                      |

The model client, AI Search, Azure SQL and the email MCP server all authenticate as this one identity.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from azure.identity import AzureCliCredential, DefaultAzureCredential, ManagedIdentityCredential

from src.config.config import get_config
from src.utils.log_helper import get_logger

logger = get_logger(__name__)

_CLASSES: dict[str, Any] = {
    "cli": AzureCliCredential,
    "managed_identity": ManagedIdentityCredential,
    "default": DefaultAzureCredential,
}


@lru_cache
def get_credential() -> Any:
    credential = _CLASSES.get(get_config().credential_type, DefaultAzureCredential)()
    logger.info("Azure credential: %s", type(credential).__name__)
    return credential
