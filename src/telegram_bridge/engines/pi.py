import base64
import mimetypes
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional
from urllib import request as urllib_request

from telegram_bridge.engines._base import (
    CompletedProcessOutputMixin,
    ProgressCallback,
    _communicate_process_with_cancel,
    _completed_process_with_output,
    _run_blocking_with_cancel,
)
from telegram_bridge.executor import ExecutorCancelledError
from telegram_bridge.engines.pi_sessions import (
    _provider_scoped_session_key,
    _safe_session_filename,
    build_session_args,
    clear_scope_session_files,
    sanitize_session_images,
)
from telegram_bridge.engines.pi_capabilities import (
    IMAGE_CAPABLE_MODEL_SUGGESTIONS,
    model_supports_images,
)
from telegram_bridge.engines.pi_command import (
    build_pi_rpc_args,
    build_pi_text_args,
)
from telegram_bridge.engines.pi_rpc import (
    IMAGE_URL_ERROR_MARKERS,
    build_rpc_prompt_json,
    extract_rpc_response,
    should_retry_pi_text_mode,
)
from telegram_bridge.engines import pi_transport

class PiEngineAdapter(CompletedProcessOutputMixin):
    engine_name = "pi"

    def _model_supports_images(self, config) -> bool:
        return model_supports_images(config)

    def _image_data_url(self, image_path: str) -> dict[str, str]:
        path = Path(image_path)
        if not path.is_file():
            raise RuntimeError(f"Pi image file not found: {image_path}")
        mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {"type": "image", "data": encoded, "mimeType": mime_type}

    def _build_pi_rpc_args(
        self,
        config,
        *,
        include_no_context_files: bool,
        session_key: Optional[str] = None,
    ) -> list[str]:
        return build_pi_rpc_args(
            config,
            include_no_context_files=include_no_context_files,
            session_key=session_key,
            build_session_args_fn=build_session_args,
        )

    def _build_pi_text_args(
        self,
        config,
        *,
        include_no_context_files: bool,
        session_key: Optional[str] = None,
    ) -> list[str]:
        return build_pi_text_args(
            config,
            include_no_context_files=include_no_context_files,
            session_key=session_key,
            build_pi_rpc_args_fn=self._build_pi_rpc_args,
        )

    @staticmethod
    @classmethod
    def clear_scope_session_files(cls, config, scope_key: str) -> int:
        return clear_scope_session_files(config, scope_key)

    def _safe_session_filename(self, session_key: str) -> str:
        return _safe_session_filename(session_key)

    def _provider_scoped_session_key(self, config, session_key: str) -> str:
        return _provider_scoped_session_key(config, session_key)

    def _build_rpc_prompt_json(
        self,
        prompt: str,
        *,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> str:
        return build_rpc_prompt_json(
            prompt,
            image_path=image_path,
            image_paths=image_paths,
            image_data_builder=self._image_data_url,
        )

    def _extract_rpc_response(self, stdout_lines: list[str]) -> str:
        return extract_rpc_response(stdout_lines)

    def _should_retry_pi_text_mode(
        self,
        exc: RuntimeError,
        *,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> bool:
        return should_retry_pi_text_mode(
            exc,
            image_path=image_path,
            image_paths=image_paths,
        )

    def _run_pi_text_local(
        self,
        config,
        prompt: str,
        session_key: Optional[str],
    ) -> str:
        return pi_transport.run_pi_text_local(
            config,
            prompt,
            session_key,
            build_pi_text_args=self._build_pi_text_args,
            subprocess_module=subprocess,
        )

    def _run_pi_text_ssh(
        self,
        config,
        prompt: str,
    ) -> str:
        return pi_transport.run_pi_text_ssh(
            config,
            prompt,
            build_pi_text_args=self._build_pi_text_args,
            subprocess_module=subprocess,
        )

    def _read_rpc_stdout(
        self,
        process: subprocess.Popen[str],
        cancel_event: Optional[threading.Event],
        timeout: int,
    ) -> list[str]:
        return pi_transport.read_rpc_stdout(
            process,
            cancel_event,
            timeout,
            time_module=time,
            executor_cancelled_error_cls=ExecutorCancelledError,
        )

    def _build_remote_command(self, config) -> str:
        return pi_transport.build_remote_command(
            config,
            build_pi_rpc_args=self._build_pi_rpc_args,
        )

    def _run_pi_ssh(
        self,
        config,
        prompt: str,
        cancel_event: Optional[threading.Event],
        *,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> str:
        return pi_transport.run_pi_ssh(
            config,
            prompt,
            cancel_event,
            image_path=image_path,
            image_paths=image_paths,
            build_rpc_prompt_json=self._build_rpc_prompt_json,
            build_remote_command_fn=self._build_remote_command,
            read_rpc_stdout_fn=self._read_rpc_stdout,
            extract_rpc_response=self._extract_rpc_response,
            should_retry_pi_text_mode=self._should_retry_pi_text_mode,
            run_pi_text_ssh_fn=self._run_pi_text_ssh,
            subprocess_module=subprocess,
            executor_cancelled_error_cls=ExecutorCancelledError,
        )

    def _local_ollama_tunnel_healthy(self, port: int) -> bool:
        return pi_transport.local_ollama_tunnel_healthy(
            port,
            socket_module=socket,
        )

    def _ensure_local_ollama_tunnel(self, config) -> None:
        pi_transport.ensure_local_ollama_tunnel(
            config,
            local_ollama_tunnel_healthy_fn=self._local_ollama_tunnel_healthy,
            subprocess_module=subprocess,
            time_module=time,
        )

    def _pi_provider_uses_ollama_tunnel(self, config) -> bool:
        return pi_transport.pi_provider_uses_ollama_tunnel(config)

    def _run_pi_local(
        self,
        config,
        prompt: str,
        session_key: Optional[str],
        cancel_event: Optional[threading.Event],
        *,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> str:
        return pi_transport.run_pi_local(
            config,
            prompt,
            session_key,
            cancel_event,
            image_path=image_path,
            image_paths=image_paths,
            pi_provider_uses_ollama_tunnel_fn=self._pi_provider_uses_ollama_tunnel,
            ensure_local_ollama_tunnel_fn=self._ensure_local_ollama_tunnel,
            build_rpc_prompt_json=self._build_rpc_prompt_json,
            build_pi_rpc_args=self._build_pi_rpc_args,
            read_rpc_stdout_fn=self._read_rpc_stdout,
            extract_rpc_response=self._extract_rpc_response,
            should_retry_pi_text_mode=self._should_retry_pi_text_mode,
            run_pi_text_local_fn=self._run_pi_text_local,
            subprocess_module=subprocess,
            executor_cancelled_error_cls=ExecutorCancelledError,
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
        del thread_id, channel_name, actor_chat_id, actor_user_id, progress_callback
        if not self._model_supports_images(config):
            if image_path or image_paths:
                model = str(getattr(config, "pi_model", "") or "").strip()
                suggestions = ", ".join(IMAGE_CAPABLE_MODEL_SUGGESTIONS)
                return self._completed_process_with_output(
                    f"Model '{model}' is text-only and does not support images. "
                    f"Use /model to switch to an image-capable model. "
                    f"Suggestions: {suggestions}."
                )
            if session_key:
                sanitize_session_images(config, session_key)
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise ExecutorCancelledError("Pi request canceled by user.")
            runner = str(getattr(config, "pi_runner", "ssh") or "ssh").strip().lower()
            if runner in {"local", "server3"}:
                output = self._run_pi_local(
                    config,
                    prompt,
                    session_key,
                    cancel_event,
                    image_path=image_path,
                    image_paths=image_paths,
                )
            elif runner in {"ssh", "server4"}:
                output = self._run_pi_ssh(
                    config,
                    prompt,
                    cancel_event,
                    image_path=image_path,
                    image_paths=image_paths,
                )
            else:
                raise RuntimeError(f"Unsupported Pi runner: {runner}")
            return self._completed_process_with_output(output)
        except ExecutorCancelledError:
            raise
        except subprocess.TimeoutExpired:
            raise
        except (RuntimeError, OSError, ValueError) as exc:
            error_msg = str(exc)
            error_lower = error_msg.lower()
            if (
                not image_path
                and not image_paths
                and session_key
                and any(marker in error_lower for marker in IMAGE_URL_ERROR_MARKERS)
            ):
                try:
                    model = str(getattr(config, "pi_model", "") or "").strip()
                    runner = str(getattr(config, "pi_runner", "ssh") or "ssh").strip().lower()
                    if runner in {"local", "server3"}:
                        output = self._run_pi_local(config, prompt, None, cancel_event)
                    else:
                        output = self._run_pi_ssh(config, prompt, cancel_event)
                    if self._model_supports_images(config):
                        note = (
                            f"(Session was reset because the previous Pi session for model "
                            f"'{model}' contained image content that the provider could not "
                            f"replay cleanly on this text message.)\n\n"
                            + output
                        )
                    else:
                        note = (
                            f"(Session was reset because the previous Pi session for model "
                            f"'{model}' contained image content, but this model is text-only "
                            f"and cannot replay it. "
                            f"Use /model to switch to an image-capable model.)\n\n"
                            + output
                        )
                    return self._completed_process_with_output(note)
                except Exception:
                    pass
            return self._completed_process_with_output(f"Pi request failed: {exc}")
