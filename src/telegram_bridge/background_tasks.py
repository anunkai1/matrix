from __future__ import annotations

import threading
from typing import Callable


def start_daemon_thread(
    target: Callable[..., None],
    *args: object,
    name: str | None = None,
) -> threading.Thread:
    worker = threading.Thread(
        target=target,
        args=args,
        daemon=True,
        name=name,
    )
    worker.start()
    return worker
