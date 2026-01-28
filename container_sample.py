import asyncio
import os

from agent_framework.observability import configure_otel_providers
from azure.ai.agentserver.agentframework import from_agent_framework
from dotenv import load_dotenv
from workflow_core import create_agents, create_workflow

load_dotenv(override=True)


async def main() -> None:
    """
    The writer and reviewer multi-agent workflow.
    This module serves as the entry point for the containerized workflow application.

    Environment variables required:
    - AZURE_AI_PROJECT_ENDPOINT: Your Microsoft Foundry project endpoint
    - AZURE_AI_MODEL_DEPLOYMENT_NAME: Your Microsoft Foundry model deployment name
    """

    # Initialize observability for visualization in local.
    # Set enable_sensitive_data to True to include sensitive information such as prompts and responses.
    if not os.getenv("MSI_ENDPOINT"):
        configure_otel_providers(
            vs_code_extension_port=4319, enable_sensitive_data=False
        )

    async with create_agents() as (writer, reviewer):
        workflow = create_workflow(writer, reviewer)
        await from_agent_framework(workflow).run_async()


if __name__ == "__main__":
    asyncio.run(main())
