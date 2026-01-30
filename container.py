import asyncio
import os

from agent_framework.azure import AzureAIAgentClient
from agent_framework.observability import configure_otel_providers
from azure.ai.agentserver.agentframework import from_agent_framework
from dotenv import load_dotenv

from runtime import build_workiq_tools, configure_logging, detect_hosted, select_credential

load_dotenv(override=True)
async def main() -> None:
    logger = configure_logging()

    # Docker/Foundry: bind to provided PORT (agent host uses ASP.NET Core under the hood)
    port = os.getenv("PORT", "8088").strip() or "8088"
    os.environ.setdefault("ASPNETCORE_URLS", f"http://+:{port}")

    is_hosted = detect_hosted()
    run_mode = os.getenv("RUN_MODE", "server").strip().lower()
    logger.debug("Runtime: RUN_MODE=%s is_hosted=%s", run_mode, is_hosted)

    # Local-only observability (optional)
    if not is_hosted:
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

    credential = select_credential(is_hosted)

    logger.debug("Credential: %s", credential.__class__.__name__)

    async with (
        credential,
        AzureAIAgentClient(
            credential=credential,
            project_endpoint=project_endpoint,
            model_deployment_name=model_deployment_name,
        ) as client,
    ):
        tools = build_workiq_tools(logger=logger, is_hosted=is_hosted)

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
            logger.debug("Server mode enabled")
            await from_agent_framework(agent, credentials=credential).run_async()


if __name__ == "__main__":
    asyncio.run(main())
