import asyncio
import logging
import os
import shutil
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from agent_framework import MCPStdioTool
from azure.identity.aio import AzureCliCredential, DefaultAzureCredential, ManagedIdentityCredential
from mcp.client.stdio import StdioServerParameters, stdio_client

from logging_utils import setup_logger
from settings import Settings

logger = setup_logger(__name__)


def disable_agentserver_tracing() -> None:
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


class TruthyAsyncCredential:
    def __init__(self, inner: Any):
        self._inner = inner

    def __bool__(self) -> bool:
        return True

    async def get_token(self, *scopes: str, **kwargs: Any):
        return await self._inner.get_token(*scopes, **kwargs)

    async def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if close is None:
            return
        result = close()
        if hasattr(result, "__await__"):
            await result

    async def __aenter__(self):
        aenter = getattr(self._inner, "__aenter__", None)
        if aenter is not None:
            await aenter()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        aexit = getattr(self._inner, "__aexit__", None)
        if aexit is not None:
            return await aexit(exc_type, exc, tb)
        return False


def credential_name(credential: Any) -> str:
    inner = getattr(credential, "_inner", None)
    return (inner or credential).__class__.__name__


def has_msi_endpoint() -> bool:
    return bool(os.getenv("MSI_ENDPOINT"))


def select_credential(has_msi: bool, settings: Settings):
    if has_msi:
        return TruthyAsyncCredential(ManagedIdentityCredential())

    if settings.use_azure_cli_credential:
        return TruthyAsyncCredential(AzureCliCredential())

    return TruthyAsyncCredential(DefaultAzureCredential())


def build_workiq_tools(*, has_msi: bool, settings: Settings):
    allow_workiq_hosted = settings.workiq_allow_hosted

    logger.info("WorkIQ: enabled=true (always) allow_hosted=%s", allow_workiq_hosted)

    if has_msi and not allow_workiq_hosted:
        logger.warning(
            "Work IQ is enabled but this runtime appears to be hosted (MSI_ENDPOINT is set). "
            "Work IQ uses delegated user auth and typically requires interactive browser/device sign-in, which is "
            "not available in headless hosted agent containers. Disabling Work IQ to avoid confusing permission errors. "
            "To force-enable anyway, set WORKIQ_ALLOW_HOSTED=true (best-effort)."
        )
        return None

    workiq_cmd = "npx"
    workiq_path = shutil.which(workiq_cmd)
    logger.debug("WorkIQ command=%s path=%s", workiq_cmd, workiq_path or "<not found>")

    if workiq_path is None:
        logger.warning(
            "Work IQ is enabled but '%s' was not found on PATH. "
            "Install Node.js (so npx is available). Disabling Work IQ for this run.",
            workiq_cmd,
        )
        return None

    tenant_id = (settings.workiq_tenant_id or "").strip()
    workiq_args = ["-y", "@microsoft/workiq"]
    if tenant_id:
        workiq_args += ["-t", tenant_id]
    workiq_args += ["mcp"]

    logger.debug("WorkIQ args=%s", workiq_args)

    capture_stderr = settings.workiq_capture_stderr
    echo_stderr = settings.workiq_echo_stderr
    stderr_log_path = settings.workiq_stderr_log_path

    tool_cls: type[MCPStdioTool]
    tool_kwargs: dict[str, Any] = {}
    if capture_stderr:
        tool_cls = LoggedMCPStdioTool
        tool_kwargs = {
            "logger": logger,
            "stderr_log_path": stderr_log_path,
            "echo_stderr": echo_stderr,
        }
        logger.info("WorkIQ: capturing MCP stderr to %s (echo=%s)", stderr_log_path, echo_stderr)
    else:
        tool_cls = MCPStdioTool

    return [
        tool_cls(
            name="workiq",
            command=workiq_cmd,
            args=workiq_args,
            description="Microsoft Work IQ MCP server (Microsoft 365 Copilot data)",
            load_prompts=False,
            **tool_kwargs,
        )
    ]


async def _tail_file_lines(
    *,
    path: str,
    logger: logging.Logger,
    prefix: str,
    stop: asyncio.Event,
    poll_seconds: float = 0.25,
) -> None:
    try:
        position = os.path.getsize(path)
    except OSError:
        position = 0

    while not stop.is_set():
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(position)
                chunk = f.read()
                position = f.tell()
        except OSError:
            chunk = ""

        if chunk:
            for line in chunk.splitlines():
                text = line.strip()
                if text:
                    logger.info("%s%s", prefix, text)

        await asyncio.sleep(poll_seconds)


class LoggedMCPStdioTool(MCPStdioTool):
    def __init__(
        self,
        *,
        logger: logging.Logger,
        stderr_log_path: str,
        echo_stderr: bool = True,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._stderr_logger = logger
        self._stderr_log_path = stderr_log_path
        self._echo_stderr = echo_stderr

    def get_mcp_client(self) -> Any:
        args: dict[str, Any] = {
            "command": self.command,
            "args": self.args,
            "env": self.env,
        }
        if self.encoding:
            args["encoding"] = self.encoding
        if getattr(self, "_client_kwargs", None):
            args.update(self._client_kwargs)

        server = StdioServerParameters(**args)

        @asynccontextmanager
        async def _client() -> AsyncGenerator[Any, None]:
            os.makedirs(os.path.dirname(self._stderr_log_path) or "/tmp", exist_ok=True)
            errlog = open(self._stderr_log_path, "a", encoding="utf-8", errors="replace", buffering=1)

            stop = asyncio.Event()
            tail_task: asyncio.Task[None] | None = None
            if self._echo_stderr:
                tail_task = asyncio.create_task(
                    _tail_file_lines(
                        path=self._stderr_log_path,
                        logger=self._stderr_logger,
                        prefix="WorkIQ(mcp stderr): ",
                        stop=stop,
                    )
                )

            try:
                async with stdio_client(server=server, errlog=errlog) as transport:
                    yield transport
            finally:
                stop.set()
                if tail_task is not None:
                    try:
                        await tail_task
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass
                try:
                    errlog.flush()
                except Exception:
                    pass
                try:
                    errlog.close()
                except Exception:
                    pass

        return _client()
