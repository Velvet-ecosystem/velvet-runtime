"""
velvet-runtime: logging/logger.py
===================================
Centralized logger factory for the Velvet runtime.

All runtime components obtain their logger via get_logger(name).
This ensures consistent formatting, level control, and output routing
across the entire runtime.

Configuration is read from config/default.yaml if available.
Falls back to safe defaults if config is unavailable at logger init time.

USAGE:
    from velvet_logging.logger import get_logger
    logger = get_logger("velvet.my_component")
    logger.info("Component initialized.")
"""

import logging
import os
import sys

# ------------------------------------------------------------------ #
# Safe defaults — used if config is not available at import time.     #
# ------------------------------------------------------------------ #
_DEFAULT_LEVEL = logging.INFO
_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DEFAULT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

_initialized = False


def _initialize_root_logger() -> None:
    """
    Configure the root logger once.
    Subsequent calls are no-ops.
    """
    global _initialized
    if _initialized:
        return

    level = _DEFAULT_LEVEL
    fmt = _DEFAULT_FORMAT
    datefmt = _DEFAULT_DATE_FORMAT
    output = "stdout"
    file_path = "logs/velvet.log"

    # Attempt to read config if available
    try:
        import yaml
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "default.yaml"
        )
        config_path = os.path.normpath(config_path)
        if os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            log_config = config.get("logging", {})
            level_str = log_config.get("level", "INFO").upper()
            level = getattr(logging, level_str, logging.INFO)
            fmt = log_config.get("format", _DEFAULT_FORMAT)
            output = log_config.get("output", "stdout")
            file_path = log_config.get("file_path", file_path)
    except Exception:
        pass  # Config unavailable — use defaults. Never crash logger init.

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove any existing handlers to avoid duplication
    root_logger.handlers.clear()

    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    if output == "file":
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        handler = logging.FileHandler(file_path, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stdout)

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger for the given component.

    Args:
        name: Dot-separated logger name, e.g. "velvet.wiring"

    Returns:
        A configured logging.Logger instance.
    """
    _initialize_root_logger()
    return logging.getLogger(name)
