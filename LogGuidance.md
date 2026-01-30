# Hosted Agent Container Logs (Quick Guidance)

This is the simplest way to view **stdout/stderr** from a Microsoft Foundry hosted agent container.

## Prereqs

- Azure CLI installed
- Logged in: `az login`

## 1) Identify these values

You need 4 values:

- `ACCOUNT_NAME`: the subdomain from your project endpoint
  - Example: for `https://agent-skill.services.ai.azure.com/...`, the account is `agent-skill`
- `PROJECT_NAME`: the project name from the project endpoint path
  - Example: for `/api/projects/agent-skill-project`, the project is `agent-skill-project`
- `AGENT_NAME`: the hosted agent name (deployment name)
- `AGENT_VERSION`: the version number you want logs for (usually the latest)

## 2) List agent versions (find the latest version)

```bash
az cognitiveservices agent list-versions \
  --account-name <ACCOUNT_NAME> \
  --project-name <PROJECT_NAME> \
  --name <AGENT_NAME> \
  -o table
```

## 3) Stream container console logs (stdout/stderr)

This streams the container **console** log stream (both stdout and stderr).

```bash
curl -sS -N --max-time 60 \
  "https://<ACCOUNT_NAME>.services.ai.azure.com/api/projects/<PROJECT_NAME>/agents/<AGENT_NAME>/versions/<AGENT_VERSION>/containers/default:logstream?kind=console&tail=300&api-version=2025-11-15-preview" \
  -H "Authorization: Bearer $(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)"
```

Notes:
- `tail` is capped (1–300)
- Max connection duration is ~10 minutes; use `--max-time` to control it

## 4) Save logs to a file (recommended)

```bash
curl -sS -N --max-time 180 \
  "https://<ACCOUNT_NAME>.services.ai.azure.com/api/projects/<PROJECT_NAME>/agents/<AGENT_NAME>/versions/<AGENT_VERSION>/containers/default:logstream?kind=console&tail=300&api-version=2025-11-15-preview" \
  -H "Authorization: Bearer $(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)" \
  | tee hosted_console.log
```

## 5) System logs (platform events)

If you want platform/system events instead of app stdout/stderr:

- Replace `kind=console` with `kind=system`.

## Example (this repo’s current values)

From your local `.env`:

- `ACCOUNT_NAME=agent-skill`
- `PROJECT_NAME=agent-skill-project`
- `AGENT_NAME=workiq-hosted-agent`

List versions:

```bash
az cognitiveservices agent list-versions \
  --account-name agent-skill \
  --project-name agent-skill-project \
  --name workiq-hosted-agent \
  -o table
```

Stream logs for version 3:

```bash
curl -sS -N --max-time 60 \
  "https://agent-skill.services.ai.azure.com/api/projects/agent-skill-project/agents/workiq-hosted-agent/versions/3/containers/default:logstream?kind=console&tail=300&api-version=2025-11-15-preview" \
  -H "Authorization: Bearer $(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)"
```

## If you get 401/403

That’s authorization/RBAC. Typically:

- Your user needs access to the Foundry project (commonly the Azure AI User role at the right scope)
- Your org policy might restrict log access

## Useful filters

```bash
tail -n 800 hosted_console.log | egrep -i "workiq|mcp|tool|exception|traceback|error|AADSTS|consent|device|login|eula|unauthorized|forbidden" | tail -n 200
```
