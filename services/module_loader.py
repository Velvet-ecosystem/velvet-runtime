"""
velvet-runtime: services/module_loader.py
==========================================
Dynamically loads Velvet modules from the /modules directory.

HARDENING DOCTRINE (Phase B/C):
- ModuleLoader accepts a pre-built _SafePublish instance.
  This is the hardened callable built inside runtime_wiring.build_runtime().
- Modules receive ONLY the _SafePublish instance. Nothing else.
- Modules do NOT receive: bus, enforcer, runtime dict, or any
  reference that could be used to reach _publish or bypass enforcement.
- Modules MUST expose register(publish) — 'publish' as the sole parameter.
- Any module whose register() declares forbidden parameters
  (enforcer, bus, runtime, event_bus) is REJECTED at load time.
- Load failures are non-fatal; they are logged and skipped.
"""

import importlib.util
import inspect
import os
import sys
from typing import List

from velvet_logging.logger import get_logger

logger = get_logger("velvet.module_loader")

# Parameters that modules must NEVER declare in register().
_FORBIDDEN_PARAMS = frozenset({"enforcer", "bus", "runtime", "event_bus"})


class ModuleLoader:
    """
    Scans a directory for Python module files and loads them.

    Accepts:
      - modules_dir:   Path to scan for .py module files.
      - safe_publish:  Pre-built _SafePublish instance.
                       This is the ONLY value passed to modules.

    Does NOT accept or store:
      - bus
      - enforcer
      - runtime dict
    """

    def __init__(self, modules_dir: str, safe_publish):
        self.modules_dir = modules_dir
        self._safe_publish = safe_publish
        self._loaded = []  # type: List[str]

    def load_all(self) -> None:
        if not os.path.isdir(self.modules_dir):
            logger.error(
                f"[BOOT] Modules directory '{self.modules_dir}' does not exist. "
                f"No modules loaded."
            )
            return

        candidates = [
            f for f in os.listdir(self.modules_dir)
            if f.endswith(".py") and not f.startswith("_")
        ]

        if not candidates:
            logger.warning(f"[BOOT] No modules found in '{self.modules_dir}'.")
            return

        for filename in sorted(candidates):
            self._load_module(filename)

        logger.info(
            f"[BOOT] Module loading complete. "
            f"Loaded: {self._loaded if self._loaded else 'none'}."
        )

    def _load_module(self, filename: str) -> None:
        module_name = filename[:-3]
        filepath = os.path.join(self.modules_dir, filename)

        logger.info(f"[BOOT] Loading module: {module_name} ({filepath})")

        try:
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                logger.warning(
                    f"[BOOT] Module '{module_name}': could not create import spec. Skipping."
                )
                return
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)
        except Exception as e:
            logger.error(
                f"[BOOT] Module '{module_name}': failed to import. Skipping. Detail: {e}"
            )
            return

        if not hasattr(mod, "register"):
            logger.warning(
                f"[BOOT] Module '{module_name}': no register() found. "
                f"Skipping. Modules must expose register(publish)."
            )
            return

        if not callable(mod.register):
            logger.warning(
                f"[BOOT] Module '{module_name}': register is not callable. Skipping."
            )
            return

        try:
            sig = inspect.signature(mod.register)
            params = set(sig.parameters.keys())
        except (ValueError, TypeError) as e:
            logger.warning(
                f"[BOOT] Module '{module_name}': could not inspect register() "
                f"signature. Skipping. Detail: {e}"
            )
            return

        found_forbidden = _FORBIDDEN_PARAMS.intersection(params)
        if found_forbidden:
            logger.error(
                f"[BOOT] Module '{module_name}': register() declares forbidden "
                f"parameter(s) {found_forbidden}. "
                f"REJECTING MODULE — modules must not accept internal runtime references."
            )
            return

        if "publish" not in params:
            logger.error(
                f"[BOOT] Module '{module_name}': register() must declare a "
                f"'publish' parameter. Skipping."
            )
            return

        try:
            mod.register(publish=self._safe_publish)
            self._loaded.append(module_name)
            logger.info(f"[BOOT] Module '{module_name}': registered successfully.")
        except Exception as e:
            logger.error(
                f"[BOOT] Module '{module_name}': register() raised an exception. "
                f"Skipping. Detail: {e}"
            )
