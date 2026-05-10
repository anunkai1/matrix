import os
import subprocess
import threading
from typing import Optional

from telegram_bridge.engines._base import ProgressCallback
from telegram_bridge.executor import run_executor
class CodexEngineAdapter:
    engine_name = "codex"
    _DISABLE_HANDOFF_ENV = "TELEGRAM_DISABLE_MAVALI_HANDOFF"

    def _is_mavali_eth_runtime(self, config) -> bool:
        if os.getenv(self._DISABLE_HANDOFF_ENV, "").strip() == "1":
            return False
        assistant_name = str(getattr(config, "assistant_name", "") or "").strip().lower()
        if assistant_name == "mavali eth":
            return True
        runtime_root = str(os.getenv("TELEGRAM_RUNTIME_ROOT", "") or "").strip().lower()
        return runtime_root.endswith("/mavali_eth")

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
        if (
            not image_path
            and not image_paths
            and self._is_mavali_eth_runtime(config)
        ):
            from telegram_bridge.engines.mavali_eth import MavaliEthEngineAdapter

            return MavaliEthEngineAdapter().run(
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
