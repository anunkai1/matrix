import re
import subprocess
import threading
import sys
from pathlib import Path
from typing import Callable, Optional, Protocol

try:
    from .executor import ExecutorProgressEvent, parse_executor_output, run_executor
except ImportError:
    from executor import ExecutorProgressEvent, parse_executor_output, run_executor

ProgressCallback = Callable[[ExecutorProgressEvent], None]


class EngineAdapter(Protocol):
    engine_name: str

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
        ...


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
            image_path=image_path,
            image_paths=image_paths,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )


class MavaliEthEngineAdapter:
    engine_name = "mavali_eth"
    _CONFIRM_INVITE_RE = re.compile(r"reply\s+`?confirm`?\s+to\s+execute", re.IGNORECASE)

    def _looks_like_help_text(self, text: str, expected_help: str) -> bool:
        normalized = str(text or "").strip()
        if normalized == expected_help:
            return True
        return normalized.startswith("I can show your wallet address") and "Examples:" in normalized

    def _invites_confirmation(self, text: str) -> bool:
        return self._CONFIRM_INVITE_RE.search(str(text or "")) is not None

    def _has_live_pending_action(self, service, session_key: str) -> bool:
        return (
            service.store.get_pending_action_envelope(session_key, now=service._now()) is not None
            or service.store.get_pending_action(session_key, now=service._now()) is not None
        )

    def _completed_process_with_output(
        self,
        *,
        thread_id: Optional[str],
        output: str,
    ) -> subprocess.CompletedProcess[str]:
        stdout = str(output or "").strip()
        if thread_id:
            stdout = f"THREAD_ID={thread_id}\nOUTPUT_BEGIN\n{stdout}"
        return subprocess.CompletedProcess(
            args=["mavali_eth"],
            returncode=0,
            stdout=stdout,
            stderr="",
        )

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
        codex_fallback = CodexEngineAdapter()
        src_root = Path(__file__).resolve().parents[1]
        if str(src_root) not in sys.path:
            sys.path.insert(0, str(src_root))
        try:
            from mavali_eth.config import MavaliEthConfig
            from mavali_eth.service import MavaliEthService
        except ImportError as exc:
            return subprocess.CompletedProcess(
                args=["mavali_eth"],
                returncode=0,
                stdout=f"mavali_eth runtime is unavailable: {exc}",
                stderr="",
            )

        if image_path or image_paths:
            return codex_fallback.run(
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

        try:
            runtime_config = MavaliEthConfig.from_env(getattr(config, "state_dir", None))
            service = MavaliEthService(runtime_config)
            resolved_session_key = session_key or f"{channel_name or 'telegram'}:default"
            output = service.handle_prompt(
                resolved_session_key,
                prompt,
                actor_chat_id=actor_chat_id,
                actor_user_id=actor_user_id,
            )
            if self._looks_like_help_text(output, service.wallet_queries.help_message()):
                fallback_result = codex_fallback.run(
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
                fallback_thread_id, fallback_output = parse_executor_output(fallback_result.stdout or "")
                if self._invites_confirmation(fallback_output) and not self._has_live_pending_action(
                    service,
                    resolved_session_key,
                ):
                    return self._completed_process_with_output(
                        thread_id=fallback_thread_id,
                        output=(
                            "I did not actually stage a pending Mavali ETH action, so `confirm` would do nothing. "
                            "Use a currently supported exact command, or implement the missing action path before "
                            "advertising confirmation."
                        ),
                    )
                return fallback_result
        except Exception as exc:
            output = str(exc) or "mavali_eth execution failed."

        return self._completed_process_with_output(thread_id=None, output=output)
