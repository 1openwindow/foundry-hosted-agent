# Hosted Agent (Container) Sample

This repo is a minimal, container-friendly Agent Framework sample that creates an Azure AI Foundry agent and runs it as a hosted agent (container). It is designed to run locally and to be deployed as a hosted agent.

## Project Structure

| File               | Description                                                         |
| ------------------ | ------------------------------------------------------------------- |
| `container.py`     | Entry point that creates the agent and starts the hosted-agent server. |
| `requirements.txt` | Lists the Python dependencies for the project.                      |
| `Dockerfile`       | Defines the container image for deployment.                         |
| `.dockerignore`    | Specifies files to ignore during container build.                   |
| `.env.example`     | Example environment configuration (copy to `.env`).                 |

## Prerequisites

- Python 3.10 or higher.
- A Microsoft Foundry Project and a model deployment.

## Setup and Installation

1. Creating virtual environments

   ```bash
    python -m venv .venv
   ```

2. Activate the virtual environment

   ```bash
   # PowerShell
   ./.venv/Scripts/Activate.ps1

   # Windows cmd
   .venv\Scripts\activate.bat

   # Unix/MacOS
   source .venv/bin/activate
   ```

3. Install dependencies

   ```bash
   pip install -r requirements.txt
   ```

4. Create or update the `.env` file with your Microsoft Foundry configuration

   ```bash
   # Your Microsoft Foundry project endpoint
   AZURE_AI_PROJECT_ENDPOINT="your-foundry-project-endpoint"

   # Your model deployment name in Microsoft Foundry
   AZURE_AI_MODEL_DEPLOYMENT_NAME="your-model-deployment-name"

   # Required: agent name
   AGENT_NAME="your-agent-name"
   ```

   Tip: you can start by copying the example file:

   ```bash
   cp .env.example .env
   ```

   **Important**: Never commit the `.env` file to version control. This repo includes a `.gitignore` rule for it.

## Local Testing

This sample authenticates using [DefaultAzureCredential](https://aka.ms/azsdk/python/identity/credential-chains#usage-guidance-for-defaultazurecredential). Ensure your development environment is configured to provide credentials via one of the supported sources, for example:

- Azure CLI (`az login`)
- Visual Studio Code account sign-in
- Visual Studio account sign-in

Confirm authentication locally (for example, az account show or az account get-access-token) before running the sample.

### Run Locally

Run the sample:

```bash
python container.py
```

Debugging tip: set `DEBUG=true` to print runtime diagnostics (credential choice, Work IQ enablement, etc.).

This starts the hosted-agent server (the same mode used in Docker/Foundry).

Credential note:

- By default, local runs use `DefaultAzureCredential`.
- If you want to explicitly use your Azure CLI login (`az login`), set:

```bash
export USE_AZURE_CLI_CREDENTIAL=true
```

### Work IQ (Microsoft 365) MCP

This sample can optionally add **Microsoft Work IQ** as an MCP tool, so the agent can pull Microsoft 365 Copilot context (emails, meetings, documents, Teams, people, etc.).

Important notes:

- Work IQ is a **Node.js** CLI/MCP server (it runs via `npx @microsoft/workiq mcp`). The provided Dockerfile installs `nodejs` + `npm`.
- Work IQ uses **delegated user auth** and may require browser-based sign-in and tenant admin consent. This can be straightforward for local development, but it may be difficult or impossible in some hosted/container environments depending on how interactive sign-in is handled.

Hosted-agent note:

- When running as a **hosted agent** (Managed Identity / `MSI_ENDPOINT` is set), this sample still enables Work IQ, but it may fail.
   - Reason: Work IQ typically needs interactive sign-in to obtain a delegated user token, but hosted agent containers are usually headless.

This sample uses `npx -y @microsoft/workiq mcp`.

Optional: specify tenant (defaults to "common"):

```bash
export WORKIQ_TENANT_ID="<your-tenant-id>"
```

Local-first setup tips:

- Ensure `npx` is available (Node.js installed). On macOS with Homebrew: `brew install node`
- On first use, accept the Work IQ EULA:

```bash
npx -y @microsoft/workiq accept-eula
```

Quick local validation (one-shot prompt mode):

Use the local playground to send a prompt such as: "List latest 3 documents on my OneDrive".

#### How to “solve” the OneDrive permission issue in hosted mode

There are only two realistic options:

1) **Use Work IQ only in local/interactive runs**
   - Keep `ENABLE_WORKIQ=true` for local development.
   - Set `ENABLE_WORKIQ=false` in hosted deployments (or rely on the default guard).

2) **If you need Microsoft 365 access in hosted deployments, build a headless-compatible integration**
   - Implement your own tool that calls Microsoft Graph using **app auth** (service principal / managed identity) or an **OBO (on-behalf-of)** flow.
   - App-only auth works well for organization-wide access patterns, but it does not naturally map to “my OneDrive” unless you provide the target user identity.
   - OBO gives true per-user access, but requires a real user-login flow in a front-end or API you control (the hosted agent runtime alone typically won’t have the user’s delegated token).

In other words: Work IQ is great for local interactive demos, but if you need per-user M365 data access from a headless hosted agent, you generally need a separate auth-enabled web/API component.

### Container Mode

To run the agent in container mode:

1. Open the Visual Studio Code Command Palette and execute the `Microsoft Foundry: Open Container Agent Playground Locally` command.
2. Execute `container.py` to initialize the containerized hosted agent.
3. Submit a request to the agent through the playground interface. For example, you may enter a prompt such as: "Create a slogan for a new electric SUV that is affordable and fun to drive."
4. Review the agent's response in the playground interface.

> **Note**: Open the local playground before starting the container agent to ensure the visualization functions correctly.

#### Run locally via Docker (no Foundry deploy)

Running the container locally is useful to reproduce “hosted-like” behavior. Note that **your host Azure login does not automatically flow into the container**.

1) Build:

```bash
docker build -t foundry-hosted-agent:dev .
```

2) Run a one-shot prompt (recommended first test):

```bash
docker run --rm -it \
   --env-file .env \
   -e DEBUG=true \
   -e RUN_MODE=prompt \
   -e PROMPT="Tell me a joke about a pirate." \
   -e AZURE_TENANT_ID="<tenant-id>" \
   -e AZURE_CLIENT_ID="<app-client-id>" \
   -e AZURE_CLIENT_SECRET="<app-client-secret>" \
   foundry-hosted-agent:dev
```

3) Run the hosted-agent server locally:

```bash
docker run --rm -it \
   --env-file .env \
   -p 8088:8088 \
   -e AZURE_TENANT_ID="<tenant-id>" \
   -e AZURE_CLIENT_ID="<app-client-id>" \
   -e AZURE_CLIENT_SECRET="<app-client-secret>" \
   foundry-hosted-agent:dev
```

Work IQ note for Docker:

- Work IQ may still fail in Docker if it requires launching a browser for sign-in. If the CLI prints a URL/code, open it on your host machine to complete sign-in.
- If Work IQ blocks your Docker validation (for example, due to auth prompts), comment out Work IQ in code or temporarily remove it from `build_workiq_tools()`.

### Tool Call Approvals

This sample does not enable any tools that require interactive approvals by default. If you add tools that require approvals, ensure your runtime configuration supports non-interactive operation when running as a hosted agent.

## Deployment

### Register Required Azure Resource Provider

Hosted Agent deployment typically creates/uses an Azure Container Registry (ACR). If your subscription hasn’t registered the ACR resource provider, deployment can fail until you register it.

**Option A — Azure Portal (easiest)**

1. Go to Azure Portal → **Subscriptions**
2. Select your subscription
3. Go to **Resource providers** (left menu)
4. Search for: `Microsoft.ContainerRegistry`
5. Select it → click **Register**
6. Wait 1–2 minutes until the status becomes **Registered**

To deploy the hosted agent:

1. Open the Visual Studio Code Command Palette and run the `Microsoft Foundry: Deploy Hosted Agent` command.

2. Follow the interactive deployment prompts. The extension will help you select or create the container files it needs:
   - It first looks for a `Dockerfile` at the repository root. If not found, you can select an existing `Dockerfile` or generate a new one.
   - If you choose to generate a Dockerfile, the extension will place the files at the repo root and open the `Dockerfile` in the editor; the deployment flow is intentionally cancelled in that case so you can review and edit the generated files before re-running the deploy command.

3. What the deploy flow does for you:
   - Creates or obtains an Azure Container Registry for the target project.
   - Builds and pushes a container image from your workspace (the build packages the workspace respecting `.dockerignore`).
   - Creates an agent version in Microsoft Foundry using the built image. If a `.env` file exists at the workspace root, the extension will parse it and include its key/value pairs as the hosted agent's `environment_variables` in the create request (these variables will be available to the agent runtime).
   - Starts the agent container on the project's capability host. If the capability host is not provisioned, the extension will prompt you to enable it and will guide you through creating it.

4. After deployment completes, the hosted agent appears under the `Hosted Agents (Preview)` section of the extension tree. You can select the agent there to view details and test it using the integrated playground.

**Important:**

- The extension only reads a `.env` file located at the first workspace folder root and forwards its content to the remote hosted agent runtime.

## MSI Configuration in the Azure Portal

This sample requires the Microsoft Foundry Project to authenticate using a Managed Identity when running remotely in Azure. Grant the project's managed identity the required permissions by assigning the built-in [Azure AI User](https://aka.ms/foundry-ext-project-role) role.

To configure the Managed Identity:

1. In the Azure Portal, open the Foundry Project.
2. Select "Access control (IAM)" from the left-hand menu.
3. Click "Add" and choose "Add role assignment".
4. In the role selection, search for and select "Azure AI User", then click "Next".
5. For "Assign access to", choose "Managed identity".
6. Click "Select members", locate the managed identity associated with your Foundry Project (you can search by the project name), then click "Select".
7. Click "Review + assign" to complete the assignment.
8. Allow a few minutes for the role assignment to propagate before running the application.

## Additional Resources

- [Microsoft Agents Framework](https://learn.microsoft.com/agent-framework/overview/agent-framework-overview)
- [What are hosted agents](https://learn.microsoft.com/azure/ai-foundry/agents/concepts/hosted-agents?view=foundry&tabs=cli)
- [Managed Identities for Azure Resources](https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/)

### References

- Work IQ MCP repo: https://github.com/microsoft/work-iq-mcp
- Work IQ overview: https://learn.microsoft.com/en-us/microsoft-365-copilot/extensibility/workiq-overview
- Agent Framework repo: https://github.com/microsoft/agent-framework
- Agent Framework overview: https://learn.microsoft.com/en-us/agent-framework/overview/agent-framework-overview
