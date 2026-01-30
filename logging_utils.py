import logging

from settings import Settings


def setup_logger(name: str) -> logging.Logger:
    """Return a logger without configuring global handlers.

    Use configure_logging() once at process startup.
    """

    return logging.getLogger(name)


def configure_logging(settings: Settings) -> None:
    """Configure global logging once for the process."""

    level_name = (settings.log_level or "").strip().upper()
    level = getattr(logging, level_name, None)
    if level is None:
        level = logging.DEBUG if (settings.debug or settings.af_debug) else logging.INFO

    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s")
