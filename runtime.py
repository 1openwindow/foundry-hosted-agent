import asyncio
import logging
import os
import shutil
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from agent_framework import MCPStdioTool
from azure.identity.aio import AzureCliCredential, DefaultAzureCredential, ManagedIdentityCredential
from mcp.client.stdio import StdioServerParameters, stdio_client


TRUTHY = {"1", "true", "yes", "on"}


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


def env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUTHY


def configure_logging() -> logging.Logger:
    level_name = os.getenv("LOG_LEVEL", "").strip().upper()
    level = getattr(logging, level_name, None)
    if level is None:
        level = logging.DEBUG if (env_truthy("DEBUG") or env_truthy("AF_DEBUG")) else logging.INFO

    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s")
    return logging.getLogger("foundry-hosted-agent")


def has_msi_endpoint() -> bool:
    return bool(os.getenv("MSI_ENDPOINT"))


def select_credential(has_msi: bool):
    if has_msi:
        return TruthyAsyncCredential(ManagedIdentityCredential())

    if env_truthy("USE_AZURE_CLI_CREDENTIAL"):
        return TruthyAsyncCredential(AzureCliCredential())

    return TruthyAsyncCredential(DefaultAzureCredential())


def build_workiq_tools(*, logger: logging.Logger, has_msi: bool):
    enable_workiq = env_truthy("ENABLE_WORKIQ")
    allow_workiq_hosted = env_truthy("WORKIQ_ALLOW_HOSTED")

    logger.info("WorkIQ: enabled=%s allow_hosted=%s", enable_workiq, allow_workiq_hosted)

    if not enable_workiq:
        return None

    if has_msi and not allow_workiq_hosted:
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

    approval_mode = os.getenv("WORKIQ_APPROVAL_MODE", "").strip() or None

    capture_stderr_env = os.getenv("WORKIQ_CAPTURE_STDERR")
    capture_stderr = True if capture_stderr_env is None else env_truthy("WORKIQ_CAPTURE_STDERR")
    echo_stderr_env = os.getenv("WORKIQ_ECHO_STDERR")
    echo_stderr = True if echo_stderr_env is None else env_truthy("WORKIQ_ECHO_STDERR")
    stderr_log_path = os.getenv("WORKIQ_STDERR_LOG_PATH", "/tmp/workiq-mcp.stderr.log").strip() or "/tmp/workiq-mcp.stderr.log"

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
            approval_mode=approval_mode,
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
