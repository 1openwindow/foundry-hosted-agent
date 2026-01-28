import os
from contextlib import asynccontextmanager

from agent_framework import WorkflowBuilder
from agent_framework.azure import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential


def get_credential():
    """Will use Managed Identity when running in Azure, otherwise falls back to DefaultAzureCredential."""
    return (
        ManagedIdentityCredential()
        if os.getenv("MSI_ENDPOINT")
        else DefaultAzureCredential()
    )


@asynccontextmanager
async def create_agents():
    async with (
        get_credential() as credential,
        AzureAIAgentClient(credential=credential) as writer_client,
        AzureAIAgentClient(credential=credential) as reviewer_client,
    ):
        writer = writer_client.create_agent(
            name="Writer",
            instructions="You are an excellent content writer. You create new content and edit contents based on the feedback.",
        )
        reviewer = reviewer_client.create_agent(
            name="Reviewer",
            instructions="You are an excellent content reviewer. Provide actionable feedback to the writer about the provided content in the most concise manner possible.",
        )
        yield writer, reviewer


def create_workflow(writer, reviewer, as_agent: bool = True):
    workflow = (
        WorkflowBuilder(name="Writer-Reviewer")
        .register_agent(lambda: writer, name="Writer", output_response=True)
        .register_agent(lambda: reviewer, name="Reviewer", output_response=True)
        .set_start_executor("Writer")
        .add_edge("Writer", "Reviewer")
        .build()
    )

    return workflow.as_agent() if as_agent else workflow
