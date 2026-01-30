import logging
import os
import shutil

from agent_framework import MCPStdioTool
from azure.identity.aio import AzureCliCredential, DefaultAzureCredential, ManagedIdentityCredential


TRUTHY = {"1", "true", "yes", "on"}


def env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUTHY


def configure_logging() -> logging.Logger:
    level_name = os.getenv("LOG_LEVEL", "").strip().upper()
    level = getattr(logging, level_name, None)
    if level is None:
        level = logging.DEBUG if (env_truthy("DEBUG") or env_truthy("AF_DEBUG")) else logging.INFO

    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s")
    return logging.getLogger("foundry-hosted-agent")


def detect_hosted() -> bool:
    return bool(os.getenv("MSI_ENDPOINT"))


def select_credential(is_hosted: bool):
    if is_hosted:
        return ManagedIdentityCredential()

    if env_truthy("USE_AZURE_CLI_CREDENTIAL"):
        return AzureCliCredential()

    return DefaultAzureCredential()


def build_workiq_tools(*, logger: logging.Logger, is_hosted: bool):
    enable_workiq = env_truthy("ENABLE_WORKIQ")
    allow_workiq_hosted = env_truthy("WORKIQ_ALLOW_HOSTED")

    logger.debug("WorkIQ: enabled=%s allow_hosted=%s", enable_workiq, allow_workiq_hosted)

    if not enable_workiq:
        return None

    if is_hosted and not allow_workiq_hosted:
        logger.warning(
            "Work IQ is enabled (ENABLE_WORKIQ=true) but this runtime appears to be hosted (MSI_ENDPOINT is set). "
            "Work IQ uses delegated user auth and typically requires interactive browser/device sign-in, which is "
            "not available in headless hosted agent containers. Disabling Work IQ to avoid confusing permission errors. "
            "To force-enable anyway, set WORKIQ_ALLOW_HOSTED=true (best-effort)."
        )
        return None

    workiq_cmd = os.getenv("WORKIQ_COMMAND", "npx").strip() or "npx"
    workiq_path = shutil.which(workiq_cmd)
    logger.debug("WorkIQ command=%s path=%s", workiq_cmd, workiq_path or "<not found>")

    if workiq_path is None:
        logger.warning(
            "Work IQ is enabled (ENABLE_WORKIQ=true) but '%s' was not found on PATH. "
            "Install Node.js (for npx) or install Work IQ globally and set WORKIQ_COMMAND=workiq. "
            "Disabling Work IQ for this run.",
            workiq_cmd,
        )
        return None

    tenant_id = os.getenv("WORKIQ_TENANT_ID", "").strip()
    workiq_args = ["-y", "@microsoft/workiq"]
    if tenant_id:
        workiq_args += ["-t", tenant_id]
    workiq_args += ["mcp"]

    logger.debug("WorkIQ args=%s", workiq_args)

    return [
        MCPStdioTool(
            name="workiq",
            command=workiq_cmd,
            args=workiq_args,
            description="Microsoft Work IQ MCP server (Microsoft 365 Copilot data)",
        )
    ]
