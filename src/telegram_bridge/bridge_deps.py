"""Explicit lazy-access facade for cross-module dependencies.

handlers.py statically imports from split modules (request_processing,
prompt_runtime, request_starts, update_flow) and re-exports their public
symbols. Those split modules can't statically import handlers back without
creating circular imports at module load time.

This module provides a single centralized lazy accessor. Split modules do:
    from . import bridge_deps as handlers
and use handlers.xxx() as before. The real handlers module is loaded on
first attribute access.
"""

import importlib
from typing import Any

_DEPS: Any = None

def _load() -> Any:
    global _DEPS
    if _DEPS is None:
        if __package__:
            _DEPS = importlib.import_module(".handlers", __package__)
        else:
            _DEPS = importlib.import_module("telegram_bridge.handlers")
    return _DEPS

def __getattr__(name: str) -> Any:
    return getattr(_load(), name)
