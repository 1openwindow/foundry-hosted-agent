import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(ValueError):
    pass


def _normalize_bool(value: str) -> str:
    return value.strip().lower()


def get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default

    value = _normalize_bool(raw)
    if value == "true":
        return True
    if value == "false":
        return False

    raise ConfigError(f"{name} must be 'true' or 'false' (got {raw!r})")


def get_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip() or default


def get_optional_str(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def get_required_str(name: str) -> str:
    value = get_optional_str(name)
    if not value:
        raise ConfigError(f"Missing required env var: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    # Server/runtime
    port: str
    enable_otel: bool
    enable_server_tracing: bool

    # Foundry
    project_endpoint: str
    model_deployment_name: str

    # Agent
    agent_name: str
    agent_instructions: str

    # Logging
    log_level: str | None
    debug: bool
    af_debug: bool

    # Auth selection (local)
    use_azure_cli_credential: bool

    # Work IQ
    workiq_tenant_id: str | None
    workiq_capture_stderr: bool
    workiq_echo_stderr: bool
    workiq_stderr_log_path: str

    def workiq_config(self) -> "WorkIQConfig":
        return WorkIQConfig(
            tenant_id=self.workiq_tenant_id,
            capture_stderr=self.workiq_capture_stderr,
            echo_stderr=self.workiq_echo_stderr,
            stderr_log_path=self.workiq_stderr_log_path,
        )


@dataclass(frozen=True)
class WorkIQConfig:
    tenant_id: str | None
    capture_stderr: bool
    echo_stderr: bool
    stderr_log_path: str


def load_settings() -> Settings:
    # Load local .env into environment for local/dev runs.
    # In hosted environments, env vars are typically injected by the platform.
    load_dotenv(override=True)

    return Settings(
        port=get_str("PORT", "8088"),
        enable_otel=get_bool("ENABLE_OTEL", False),
        enable_server_tracing=get_bool("ENABLE_SERVER_TRACING", False),
        project_endpoint=get_required_str("AZURE_AI_PROJECT_ENDPOINT"),
        model_deployment_name=get_required_str("AZURE_AI_MODEL_DEPLOYMENT_NAME"),
        agent_name=get_required_str("AGENT_NAME"),
        agent_instructions=get_str("AGENT_INSTRUCTIONS", "You are good at telling jokes."),
        log_level=get_optional_str("LOG_LEVEL"),
        debug=get_bool("DEBUG", False),
        af_debug=get_bool("AF_DEBUG", False),
        use_azure_cli_credential=get_bool("USE_AZURE_CLI_CREDENTIAL", False),
        workiq_tenant_id=get_optional_str("WORKIQ_TENANT_ID"),
        workiq_capture_stderr=get_bool("WORKIQ_CAPTURE_STDERR", True),
        workiq_echo_stderr=get_bool("WORKIQ_ECHO_STDERR", True),
        workiq_stderr_log_path=get_str("WORKIQ_STDERR_LOG_PATH", "/tmp/workiq-mcp.stderr.log"),
    )
