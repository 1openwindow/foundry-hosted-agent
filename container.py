import asyncio
import os
import sys
from typing import Any

from agent_framework import AgentProtocol, HostedMCPTool
from agent_framework.observability import configure_otel_providers
from agent_framework.azure import AzureAIAgentClient
from azure.ai.agentserver.agentframework import from_agent_framework
from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential
from dotenv import load_dotenv

load_dotenv(override=True)


def _parse_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def get_credential():
    return ManagedIdentityCredential() if os.getenv("MSI_ENDPOINT") else DefaultAzureCredential()


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


class ApprovalHandlingAgent(AgentProtocol):
    def __init__(self, agent: AgentProtocol):
        self._agent = agent

    @property
    def name(self) -> str:  # type: ignore[override]
        return getattr(self._agent, "name", type(self._agent).__name__)

    def get_new_thread(self, **kwargs: Any):
        return self._agent.get_new_thread(**kwargs)

    async def run(self, messages=None, *, thread=None, **kwargs: Any):
        from agent_framework import ChatMessage

        kwargs.setdefault("store", True)
        result = await self._agent.run(messages, thread=thread, **kwargs)
        while getattr(result, "user_input_requests", None):
            new_input: list[Any] = []
            for user_input_needed in result.user_input_requests:
                print(
                    f"User Input Request for function from {self.name}: {user_input_needed.function_call.name}"
                    f" with arguments: {user_input_needed.function_call.arguments}"
                )
                approved = _get_approval()
                new_input.append(
                    ChatMessage(
                        role="user",
                        contents=[user_input_needed.create_response(approved)],
                    )
                )
            result = await self._agent.run(new_input, thread=thread, **kwargs)
        return result

    def run_stream(self, messages=None, *, thread=None, **kwargs: Any):
        return self._agent.run_stream(messages, thread=thread, **kwargs)


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


async def main() -> None:
    """Agent container entrypoint (starts server)."""

    project_endpoint = _require_env("AZURE_AI_PROJECT_ENDPOINT")
    model_deployment_name = _require_env("AZURE_AI_MODEL_DEPLOYMENT_NAME")

    # Initialize observability for visualization in local.
    # Set enable_sensitive_data to True to include sensitive information such as prompts and responses.
    if not os.getenv("MSI_ENDPOINT"):
        configure_otel_providers(
            vs_code_extension_port=4319, enable_sensitive_data=False
        )

    async with (
        get_credential() as credential,
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
                approval_mode="never_require",
            ),
        )

        await from_agent_framework(agent, credentials=credential).run_async()


if __name__ == "__main__":
    asyncio.run(main())
