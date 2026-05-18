import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from telegram_bridge.engines._base import ProgressCallback
from telegram_bridge.engines.codex import CodexEngineAdapter
from telegram_bridge.executor import ExecutorCancelledError, parse_executor_output
from mavali_eth.service_runtime import extract_current_message_text


class MavaliEthEngineAdapter:
    engine_name = "mavali_eth"
    _CONFIRM_INVITE_RE = re.compile(r"reply\s+`?confirm`?\s+to\s+execute", re.IGNORECASE)
    _DISABLE_HANDOFF_ENV = "TELEGRAM_DISABLE_MAVALI_HANDOFF"
    _TRANSLATION_SENTINEL = "NO_MAVALI_COMMAND"

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

    def _build_translation_prompt(self, prompt: str) -> str:
        request_text = extract_current_message_text(prompt).strip() or str(prompt or "").strip()
        return (
            "Translate the user request into exactly one canonical Mavali ETH command if and only if it is clearly a "
            "wallet, Aster, Hyperliquid, or backburner request. Output the command only. If it is not clearly a "
            f"Mavali request, output exactly {self._TRANSLATION_SENTINEL}.\n\n"
            "Examples:\n"
            "- \"what's the wallet status\" -> status\n"
            "- \"refresh that status\" -> status\n"
            "- \"show my aster open orders\" -> show aster open orders\n"
            "- \"turn off the XAG backburner\" -> cancel backburner for XAGUSDT\n"
            "- \"disarm 1h backburner for xagusdt\" -> cancel backburner for XAGUSDT\n"
            "- \"arm 1h backburner for xagusdt\" -> arm 1h backburner for XAGUSDT\n"
            "- \"re-enable the xag backburner\" -> rearm backburner for XAGUSDT\n"
            "- \"rerun the silver backburner cycle\" -> run backburner cycle for XAGUSDT\n"
            "- \"arm a 1h xag backburner for 300 usdt\" -> backburner buy XAGUSDT at 1h for total 300 USDT\n"
            "- \"how are you\" -> NO_MAVALI_COMMAND\n\n"
            f"User request:\n{request_text}"
        )

    def _extract_translated_command(self, text: str) -> str:
        normalized = str(text or "").strip()
        if not normalized:
            return ""
        if normalized.startswith("```") and normalized.endswith("```"):
            normalized = normalized.strip("`").strip()
        first_line = normalized.splitlines()[0].strip()
        return first_line.strip("`").strip()

    def _ensure_runtime_import_path(self) -> None:
        candidate_roots: list[Path] = []
        runtime_root_raw = os.getenv("TELEGRAM_RUNTIME_ROOT", "").strip()
        if runtime_root_raw:
            candidate_roots.append(Path(runtime_root_raw).expanduser() / "src")
        candidate_roots.append(Path("/home/architect/gitea-server2/mavali_eth/src"))
        shared_src_root = Path(__file__).resolve().parents[2]
        candidate_roots.append(shared_src_root)
        for candidate in reversed(candidate_roots):
            if not candidate.is_dir():
                continue
            candidate_text = str(candidate)
            if candidate_text in sys.path:
                sys.path.remove(candidate_text)
            sys.path.insert(0, candidate_text)

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
        original_prompt: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> subprocess.CompletedProcess[str]:
        del original_prompt
        codex_fallback = CodexEngineAdapter()
        self._ensure_runtime_import_path()
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
            return self._run_codex_fallback(
                codex_fallback,
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
                translation_result = self._run_codex_fallback(
                    codex_fallback,
                    config=config,
                    prompt=self._build_translation_prompt(prompt),
                    thread_id=None,
                    session_key=None,
                    channel_name=channel_name,
                    actor_chat_id=actor_chat_id,
                    actor_user_id=actor_user_id,
                    image_path=None,
                    image_paths=None,
                    progress_callback=progress_callback,
                    cancel_event=cancel_event,
                )
                _, translation_output = parse_executor_output(translation_result.stdout or "")
                translated_command = self._extract_translated_command(translation_output)
                if (
                    translated_command
                    and translated_command != self._TRANSLATION_SENTINEL
                ):
                    translated_result = service.handle_prompt(
                        resolved_session_key,
                        translated_command,
                        actor_chat_id=actor_chat_id,
                        actor_user_id=actor_user_id,
                    )
                    if not self._looks_like_help_text(translated_result, service.wallet_queries.help_message()):
                        return self._completed_process_with_output(thread_id=None, output=translated_result)
                fallback_result = self._run_codex_fallback(
                    codex_fallback,
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
        except (ExecutorCancelledError, subprocess.TimeoutExpired):
            raise
        except Exception as exc:
            output = str(exc) or "mavali_eth execution failed."

        return self._completed_process_with_output(thread_id=None, output=output)

    def _run_codex_fallback(
        self,
        codex_fallback: CodexEngineAdapter,
        **kwargs,
    ) -> subprocess.CompletedProcess[str]:
        previous = os.getenv(self._DISABLE_HANDOFF_ENV)
        os.environ[self._DISABLE_HANDOFF_ENV] = "1"
        try:
            return codex_fallback.run(**kwargs)
        finally:
            if previous is None:
                os.environ.pop(self._DISABLE_HANDOFF_ENV, None)
            else:
                os.environ[self._DISABLE_HANDOFF_ENV] = previous
