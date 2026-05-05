import subprocess
import threading
from typing import Optional

from telegram_bridge.engines._base import ProgressCallback
from telegram_bridge.executor import run_executor


class CodexEngineAdapter:
    engine_name = "codex"

    def run(
        self,
        config,
        prompt: str,
        thread_id: Optional[str],
        session_key: Optional[str] = None,
        channel_name: Optional[str] = None,
        actor_chat_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> subprocess.CompletedProcess[str]:
        return run_executor(
            config=config,
            prompt=prompt,
            thread_id=thread_id,
            session_key=session_key,
            channel_name=channel_name,
            actor_chat_id=actor_chat_id,
            actor_user_id=actor_user_id,
            image_path=image_path,
            image_paths=image_paths,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )
