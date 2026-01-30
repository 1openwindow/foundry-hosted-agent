import asyncio
import os
import shutil

from agent_framework import MCPStdioTool
from agent_framework.azure import AzureAIAgentClient
from agent_framework.observability import configure_otel_providers
from azure.ai.agentserver.agentframework import from_agent_framework
from azure.identity.aio import AzureCliCredential, DefaultAzureCredential, ManagedIdentityCredential
from dotenv import load_dotenv

load_dotenv(override=True)

async def main() -> None:
    # Docker/Foundry: bind to provided PORT (agent host uses ASP.NET Core under the hood)
    port = os.getenv("PORT", "8088").strip() or "8088"
    os.environ.setdefault("ASPNETCORE_URLS", f"http://+:{port}")

    is_hosted = bool(os.getenv("MSI_ENDPOINT"))

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

    # Credential: managed identity in Foundry/Azure; Azure CLI credential if requested; otherwise default chain.
    credential = (
        ManagedIdentityCredential()
        if is_hosted
        else AzureCliCredential()
        if os.getenv("USE_AZURE_CLI_CREDENTIAL", "").strip().lower() in {"1", "true", "yes"}
        else DefaultAzureCredential()
    )

    async with (
        credential,
        AzureAIAgentClient(
            credential=credential,
            project_endpoint=project_endpoint,
            model_deployment_name=model_deployment_name,
        ) as client,
    ):
        tools = None
        enable_workiq = os.getenv("ENABLE_WORKIQ", "").strip().lower() in {"1", "true", "yes"}
        allow_workiq_hosted = os.getenv("WORKIQ_ALLOW_HOSTED", "").strip().lower() in {"1", "true", "yes"}
        if enable_workiq and is_hosted and not allow_workiq_hosted:
            print(
                "Work IQ is enabled (ENABLE_WORKIQ=true) but this runtime appears to be hosted (MSI_ENDPOINT is set).\n"
                "Work IQ uses delegated user auth and typically requires interactive browser/device sign-in, which is\n"
                "not available in headless hosted agent containers. Disabling Work IQ to avoid confusing permission errors.\n"
                "To force-enable anyway, set WORKIQ_ALLOW_HOSTED=true (best-effort).",
                flush=True,
            )
            enable_workiq = False

        if enable_workiq:
            workiq_cmd = os.getenv("WORKIQ_COMMAND", "npx").strip() or "npx"
            tenant_id = os.getenv("WORKIQ_TENANT_ID", "").strip()

            if shutil.which(workiq_cmd) is None:
                print(
                    f"Work IQ is enabled (ENABLE_WORKIQ=true) but '{workiq_cmd}' was not found on PATH.\n"
                    "Install Node.js (for npx) or install Work IQ globally and set WORKIQ_COMMAND=workiq.\n"
                    "Disabling Work IQ for this run.",
                    flush=True,
                )
                enable_workiq = False

        if enable_workiq:
            workiq_args = ["-y", "@microsoft/workiq"]
            if tenant_id:
                workiq_args += ["-t", tenant_id]
            workiq_args += ["mcp"]

            tools = [
                MCPStdioTool(
                    name="workiq",
                    command=workiq_cmd,
                    args=workiq_args,
                    description="Microsoft Work IQ MCP server (Microsoft 365 Copilot data)",
                )
            ]

        agent = client.create_agent(
            name=os.getenv("AGENT_NAME", "HostedAgent"),
            instructions=os.getenv("AGENT_INSTRUCTIONS", "You are good at telling jokes."),
            tools=tools,
        )

        print(f"Agent name: {getattr(agent, 'name', '<unknown>')}")

        # Default: run as hosted agent server for Docker/Foundry.
        if os.getenv("RUN_MODE", "server").strip().lower() == "prompt":
            result = await agent.run(os.getenv("PROMPT", "Tell me a joke about a pirate."))
            print(getattr(result, "text", result))
        else:
            await from_agent_framework(agent, credentials=credential).run_async()


if __name__ == "__main__":
    asyncio.run(main())
