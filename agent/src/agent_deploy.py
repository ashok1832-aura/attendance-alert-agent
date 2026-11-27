"""Register the pushed image as a new Foundry Hosted Agent version.

    uv run python -m src.agent_deploy        # uses ACR_NAME and IMAGE_TAG from .env

The container gets its settings as environment variables (Config.hosted_env); no secrets are passed.
"""

import sys

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointProtocol,
    ContainerConfiguration,
    HostedAgentDefinition,
    ProtocolVersionRecord,
)

from src.agent.builder import DESCRIPTION
from src.agent.credential import get_credential
from src.config.config import get_config
from src.utils.log_helper import get_logger

logger = get_logger(__name__)


def deploy() -> None:
    cfg = get_config()
    if not cfg.acr_name:
        raise RuntimeError("ACR_NAME is required (registry name without .azurecr.io)")
    image = f"{cfg.acr_name}.azurecr.io/{cfg.name}:{cfg.image_tag}"

    project = AIProjectClient(endpoint=cfg.foundry_project_endpoint, credential=get_credential(),
                              allow_preview=True)
    version = project.agents.create_version(
        agent_name=cfg.name,
        description=DESCRIPTION,
        definition=HostedAgentDefinition(
            protocol_versions=[ProtocolVersionRecord(protocol=AgentEndpointProtocol.RESPONSES, version="1.0.0")],
            cpu="1",
            memory="2Gi",
            container_configuration=ContainerConfiguration(image=image),
            environment_variables=cfg.hosted_env(),
        ),
    )
    logger.info("Registered %s version %s (image=%s). Check it shows 'Active' in the Foundry portal.",
                cfg.name, version.version, image)


if __name__ == "__main__":
    try:
        deploy()
    except Exception:
        logger.exception("Deployment failed")
        sys.exit(1)
