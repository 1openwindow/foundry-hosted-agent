import asyncio
import os

from agent_framework.azure import AzureAIAgentClient
from agent_framework.observability import configure_otel_providers
from azure.ai.agentserver.agentframework import from_agent_framework
from dotenv import load_dotenv

from runtime import build_workiq_tools, configure_logging, credential_name, has_msi_endpoint, select_credential

load_dotenv(override=True)


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _disable_agentserver_tracing(logger) -> None:
    """Disable agentserver tracing init.

    The agentserver Agent Framework adapter may schedule an async tracing setup task that
    can fail noisily in local dev environments. This disables that init path.
    """

    try:
        from opentelemetry import trace
        from azure.ai.agentserver.agentframework.agent_framework import AgentFrameworkCBAgent

        def _noop_init_tracing(self):
            self.tracer = trace.get_tracer(__name__)

        AgentFrameworkCBAgent.init_tracing = _noop_init_tracing  # type: ignore[method-assign]
        logger.info("Tracing disabled (ENABLE_SERVER_TRACING not set).")
    except Exception as exc:
        logger.warning("Failed to disable tracing: %s", exc)


async def main() -> None:
    logger = configure_logging()

    # Docker/Foundry: bind to provided PORT (agent host uses ASP.NET Core under the hood)
    port = os.getenv("PORT", "8088").strip() or "8088"
    os.environ.setdefault("ASPNETCORE_URLS", f"http://+:{port}")

    has_msi = has_msi_endpoint()
    run_mode = os.getenv("RUN_MODE", "server").strip().lower()
    logger.info("Runtime: RUN_MODE=%s has_msi_endpoint=%s", run_mode, has_msi)

    # Local-only observability (optional)
    if not has_msi and _env_truthy("ENABLE_OTEL"):
        try:
            configure_otel_providers(vs_code_extension_port=4319, enable_sensitive_data=False)
        except Exception:
            pass

    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    model_deployment_name = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    if not project_endpoint or not model_deployment_name:
        raise SystemExit(
            "Missing required env vars: AZURE_AI_PROJECT_ENDPOINT and AZURE_AI_MODEL_DEPLOYMENT_NAME"
        )

    logger.debug("AZURE_AI_PROJECT_ENDPOINT=%s", (project_endpoint or "").split("?")[0])
    logger.debug("AZURE_AI_MODEL_DEPLOYMENT_NAME=%s", model_deployment_name)

    credential = select_credential(has_msi)

    logger.info("Credential: %s", credential_name(credential))

    async with (
        credential,
        AzureAIAgentClient(
            credential=credential,
            project_endpoint=project_endpoint,
            model_deployment_name=model_deployment_name,
        ) as client,
    ):
        tools = build_workiq_tools(logger=logger, has_msi=has_msi)

        agent = client.create_agent(
            name=os.getenv("AGENT_NAME", "HostedAgent"),
            instructions=os.getenv("AGENT_INSTRUCTIONS", "You are good at telling jokes."),
            tools=tools,
        )

        logger.info("Agent name: %s", getattr(agent, "name", "<unknown>"))

        # Default: run as hosted agent server for Docker/Foundry.
        if run_mode == "prompt":
            prompt = os.getenv("PROMPT", "Tell me a joke about a pirate.")
            logger.debug("Prompt mode enabled")
            result = await agent.run(prompt)
            print(getattr(result, "text", result))
        else:
            if not has_msi and not _env_truthy("ENABLE_SERVER_TRACING"):
                _disable_agentserver_tracing(logger)
            logger.debug("Server mode enabled")
            await from_agent_framework(agent, credentials=credential).run_async()


if __name__ == "__main__":
    asyncio.run(main())
