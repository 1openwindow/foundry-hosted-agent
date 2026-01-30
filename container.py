import asyncio
import os

from agent_framework.azure import AzureAIAgentClient
from agent_framework.observability import configure_otel_providers
from azure.ai.agentserver.agentframework import from_agent_framework

from runtime import (
    build_workiq_tools,
    configure_logging,
    credential_name,
    disable_agentserver_tracing,
    has_msi_endpoint,
    select_credential,
)
from settings import ConfigError, load_settings


async def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        raise SystemExit(str(exc))

    logger = configure_logging(settings)

    # Docker/Foundry: bind to provided PORT (agent host uses ASP.NET Core under the hood)
    os.environ.setdefault("ASPNETCORE_URLS", f"http://+:{settings.port}")

    has_msi = has_msi_endpoint()
    logger.info("Runtime: has_msi_endpoint=%s", has_msi)

    # Local-only observability (optional)
    if not has_msi and settings.enable_otel:
        try:
            configure_otel_providers(vs_code_extension_port=4319, enable_sensitive_data=False)
        except Exception:
            pass

    logger.debug("AZURE_AI_PROJECT_ENDPOINT=%s", (settings.project_endpoint or "").split("?")[0])
    logger.debug("AZURE_AI_MODEL_DEPLOYMENT_NAME=%s", settings.model_deployment_name)

    credential = select_credential(has_msi, settings)

    logger.info("Credential: %s", credential_name(credential))

    async with (
        credential,
        AzureAIAgentClient(
            credential=credential,
            project_endpoint=settings.project_endpoint,
            model_deployment_name=settings.model_deployment_name,
        ) as client,
    ):
        tools = build_workiq_tools(logger=logger, has_msi=has_msi, settings=settings)

        agent = client.create_agent(
            name=settings.agent_name,
            instructions=settings.agent_instructions,
            tools=tools,
        )

        logger.info("Agent name: %s", getattr(agent, "name", "<unknown>"))

        # Always run as hosted agent server for Docker/Foundry.
        if not has_msi and not settings.enable_server_tracing:
            disable_agentserver_tracing(logger)
        logger.debug("Server mode enabled")
        await from_agent_framework(agent, credentials=credential).run_async()


if __name__ == "__main__":
    asyncio.run(main())
