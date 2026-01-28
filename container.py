import asyncio
import os
import sys
from typing import Any

from agent_framework import AgentProtocol, AgentRunResponse, AgentThread, HostedMCPTool
from agent_framework.observability import configure_otel_providers
from agent_framework_azure_ai import AzureAIAgentClient
from azure.core.exceptions import ResourceNotFoundError
from azure.identity.aio import AzureCliCredential, DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv(override=True)


def _parse_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_approval() -> bool:
    if _parse_bool_env("MCP_AUTO_APPROVE", default=False):
        return True
    if not sys.stdin.isatty():
        raise RuntimeError(
            "Function-call approval required, but stdin is not interactive. "
            "Set MCP_AUTO_APPROVE=true to allow hosted MCP tool calls in non-interactive runs."
        )

    user_approval = input("Approve function call? (y/n): ")
    return user_approval.strip().lower() in {"y", "yes"}


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise SystemExit(
            f"Missing required environment variable: {name}\n\n"
            "Set these in your .env (recommended) or shell:\n"
            "- AZURE_AI_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>\n"
            "- AZURE_AI_MODEL_DEPLOYMENT_NAME=<your-model-deployment>\n"
        )
    return value.strip()


async def handle_approvals_with_thread(
    query: str, agent: "AgentProtocol", thread: "AgentThread"
) -> AgentRunResponse:
    """Rerun the agent until all tool call approvals are resolved."""
    from agent_framework import ChatMessage

    result = await agent.run(query, thread=thread, store=True)
    while len(result.user_input_requests) > 0:
        new_input: list[Any] = []
        for user_input_needed in result.user_input_requests:
            print(
                f"User Input Request for function from {agent.name}: {user_input_needed.function_call.name}"
                f" with arguments: {user_input_needed.function_call.arguments}"
            )
            approved = _get_approval()
            new_input.append(
                ChatMessage(
                    role="user",
                    contents=[user_input_needed.create_response(approved)],
                )
            )
        result = await agent.run(new_input, thread=thread, store=True)
    return result


async def main() -> None:
    """Azure AI Agent using a hosted MCP tool (Microsoft Learn MCP).

    Notes:
        - Requires `AZURE_AI_PROJECT_ENDPOINT` and `AZURE_AI_MODEL_DEPLOYMENT_NAME`.
        - Auth defaults to `DefaultAzureCredential` when running in managed identity/workload identity contexts;
            otherwise it uses `AzureCliCredential` (requires `az login`).
        - Hosted MCP tool calls may request approval. For non-interactive runs, set `MCP_AUTO_APPROVE=true`.
    """

    project_endpoint = _require_env("AZURE_AI_PROJECT_ENDPOINT")
    model_deployment_name = _require_env("AZURE_AI_MODEL_DEPLOYMENT_NAME")

    print(f"Using AZURE_AI_PROJECT_ENDPOINT={project_endpoint}")
    print(f"Using AZURE_AI_MODEL_DEPLOYMENT_NAME={model_deployment_name}")

    # Initialize observability for visualization in local.
    # Set enable_sensitive_data to True to include sensitive information such as prompts and responses.
    if not os.getenv("MSI_ENDPOINT"):
        configure_otel_providers(
            vs_code_extension_port=4319, enable_sensitive_data=False
        )

    credential = DefaultAzureCredential() if os.getenv("MSI_ENDPOINT") else AzureCliCredential()

    async with (
        credential,
        AzureAIAgentClient(
            credential=credential,
            project_endpoint=project_endpoint,
            model_deployment_name=model_deployment_name,
        ) as client,
    ):
        agent = client.create_agent(
            name="DocsAgent",
            instructions="You are a helpful assistant that can help with Microsoft documentation questions.",
            tools=HostedMCPTool(
                name="Microsoft Learn MCP",
                url="https://learn.microsoft.com/api/mcp",
            ),
        )
        thread = agent.get_new_thread()

        queries = [
            "How to create an Azure storage account using az cli?",
        ]

        for idx, query in enumerate(queries, start=1):
            print(f"User ({idx}): {query}")
            result = await handle_approvals_with_thread(query, agent, thread)
            print(f"{agent.name}: {result}\n")
            if idx != len(queries):
                print("\n=======================================\n")


if __name__ == "__main__":
    asyncio.run(main())
