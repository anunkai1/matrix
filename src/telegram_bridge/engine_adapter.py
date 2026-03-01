import subprocess
from typing import Callable, Optional, Protocol

try:
    from .executor import ExecutorProgressEvent, run_executor
except ImportError:
    from executor import ExecutorProgressEvent, run_executor

ProgressCallback = Callable[[ExecutorProgressEvent], None]


class EngineAdapter(Protocol):
    engine_name: str

    def run(
        self,
        config,
        prompt: str,
        thread_id: Optional[str],
        image_path: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> subprocess.CompletedProcess[str]:
        ...


class CodexEngineAdapter:
    engine_name = "codex"

    def run(
        self,
        config,
        prompt: str,
        thread_id: Optional[str],
        image_path: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> subprocess.CompletedProcess[str]:
        return run_executor(
            config=config,
            prompt=prompt,
            thread_id=thread_id,
            image_path=image_path,
            progress_callback=progress_callback,
        )
