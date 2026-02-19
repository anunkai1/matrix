#!/usr/bin/env python3
"""Home Assistant conversation helpers for the Telegram bridge."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional, Set
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HAControlError(RuntimeError):
    """Raised for user-facing HA conversation/execution issues."""


@dataclass
class HAConfig:
    base_url: str
    token: str
    conversation_agent_id: str
    language: str
    allowed_domains: Set[str]
    allowed_entities: Set[str]


class HomeAssistantClient:
    def __init__(self, config: HAConfig, timeout_seconds: int = 15) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds

    def _request(
        self,
        path: str,
        method: str = "GET",
        payload: Optional[Dict[str, object]] = None,
    ) -> object:
        body = None
        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "Content-Type": "application/json",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        endpoint = f"{self.config.base_url}{path}"
        req = Request(endpoint, data=body, method=method, headers=headers)
        with urlopen(req, timeout=self.timeout_seconds) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw)

    def process_conversation(
        self,
        text: str,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, object]:
        payload: Dict[str, object] = {"text": text}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if self.config.language:
            payload["language"] = self.config.language
        if self.config.conversation_agent_id:
            payload["agent_id"] = self.config.conversation_agent_id

        data = self._request("/api/conversation/process", method="POST", payload=payload)
        if not isinstance(data, dict):
            raise HAControlError("Home Assistant returned invalid conversation payload.")
        return data


def _parse_bool(raw: str, default: bool = False) -> bool:
    if raw is None:
        return default
    value = raw.strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _parse_csv_set(raw: str) -> Set[str]:
    values = set()
    for part in (raw or "").split(","):
        item = part.strip().lower()
        if item:
            values.add(item)
    return values


def load_ha_config(_state_dir: str) -> Optional[HAConfig]:
    enabled = _parse_bool(os.getenv("TELEGRAM_HA_ENABLED", ""), default=False)
    base_url = os.getenv("TELEGRAM_HA_BASE_URL", "").strip().rstrip("/")
    token = os.getenv("TELEGRAM_HA_TOKEN", "").strip()

    if not enabled and not (base_url and token):
        return None

    if not base_url:
        raise ValueError("TELEGRAM_HA_BASE_URL is required when HA integration is enabled")
    if not token:
        raise ValueError("TELEGRAM_HA_TOKEN is required when HA integration is enabled")

    conversation_agent_id = os.getenv("TELEGRAM_HA_CONVERSATION_AGENT_ID", "").strip()
    language = os.getenv("TELEGRAM_HA_LANGUAGE", "en").strip()

    # Keep these envs for backward compatibility / operator visibility.
    allowed_domains = _parse_csv_set(
        os.getenv(
            "TELEGRAM_HA_ALLOWED_DOMAINS",
            "climate,switch,light,water_heater,input_boolean",
        )
    )
    allowed_entities = _parse_csv_set(os.getenv("TELEGRAM_HA_ALLOWED_ENTITIES", ""))

    return HAConfig(
        base_url=base_url,
        token=token,
        conversation_agent_id=conversation_agent_id,
        language=language,
        allowed_domains=allowed_domains,
        allowed_entities=allowed_entities,
    )


def extract_conversation_id(payload: Dict[str, object]) -> Optional[str]:
    value = payload.get("conversation_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def extract_conversation_reply(payload: Dict[str, object]) -> str:
    response = payload.get("response")
    if isinstance(response, dict):
        speech = response.get("speech")
        if isinstance(speech, dict):
            plain = speech.get("plain")
            if isinstance(plain, dict):
                text = plain.get("speech")
                if isinstance(text, str) and text.strip():
                    return text.strip()

        # Some agents return direct text blocks.
        for key in ("text", "response_text", "error"):
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    for key in ("error", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return "Home Assistant did not return a response message."


def is_ha_network_error(exc: Exception) -> bool:
    return isinstance(exc, (HTTPError, URLError, TimeoutError))
