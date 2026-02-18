#!/usr/bin/env python3
"""Home Assistant control helpers for the Telegram bridge."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HAControlError(RuntimeError):
    """Raised for user-facing HA planning/execution issues."""


@dataclass
class HAConfig:
    base_url: str
    token: str
    approval_ttl_seconds: int
    temp_min_c: float
    temp_max_c: float
    allowed_domains: Set[str]
    allowed_entities: Set[str]
    aliases_path: str
    followup_script_entity: str
    solar_sensor_entity: str
    solar_excess_threshold_watts: float


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

    def get_states(self) -> List[Dict[str, object]]:
        data = self._request("/api/states", method="GET")
        if not isinstance(data, list):
            raise HAControlError("Home Assistant returned invalid states payload.")
        out: List[Dict[str, object]] = []
        for item in data:
            if isinstance(item, dict):
                out.append(item)
        return out

    def get_state(self, entity_id: str) -> Optional[Dict[str, object]]:
        try:
            data = self._request(f"/api/states/{entity_id}", method="GET")
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        if not isinstance(data, dict):
            return None
        return data

    def call_service(self, domain: str, service: str, data: Dict[str, object]) -> None:
        self._request(
            f"/api/services/{domain}/{service}",
            method="POST",
            payload=data,
        )


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


def _normalize_alias(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _parse_float(raw: str, label: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{label} must be a number") from exc


def load_ha_config(state_dir: str) -> Optional[HAConfig]:
    enabled = _parse_bool(os.getenv("TELEGRAM_HA_ENABLED", ""), default=False)
    base_url = os.getenv("TELEGRAM_HA_BASE_URL", "").strip().rstrip("/")
    token = os.getenv("TELEGRAM_HA_TOKEN", "").strip()

    if not enabled and not (base_url and token):
        return None
    enabled = True

    if enabled and not base_url:
        raise ValueError("TELEGRAM_HA_BASE_URL is required when HA integration is enabled")
    if enabled and not token:
        raise ValueError("TELEGRAM_HA_TOKEN is required when HA integration is enabled")

    approval_ttl_seconds = int(os.getenv("TELEGRAM_HA_APPROVAL_TTL_SECONDS", "300"))
    if approval_ttl_seconds < 30:
        raise ValueError("TELEGRAM_HA_APPROVAL_TTL_SECONDS must be >= 30")

    temp_min_c = _parse_float(os.getenv("TELEGRAM_HA_TEMP_MIN_C", "16"), "TELEGRAM_HA_TEMP_MIN_C")
    temp_max_c = _parse_float(os.getenv("TELEGRAM_HA_TEMP_MAX_C", "30"), "TELEGRAM_HA_TEMP_MAX_C")
    if temp_min_c >= temp_max_c:
        raise ValueError("TELEGRAM_HA_TEMP_MIN_C must be lower than TELEGRAM_HA_TEMP_MAX_C")

    allowed_domains = _parse_csv_set(
        os.getenv(
            "TELEGRAM_HA_ALLOWED_DOMAINS",
            "climate,switch,light,water_heater,input_boolean",
        )
    )
    if not allowed_domains:
        raise ValueError("TELEGRAM_HA_ALLOWED_DOMAINS cannot be empty")

    allowed_entities = _parse_csv_set(os.getenv("TELEGRAM_HA_ALLOWED_ENTITIES", ""))

    aliases_path = os.getenv(
        "TELEGRAM_HA_ALIASES_PATH",
        os.path.join(state_dir, "ha_aliases.json"),
    ).strip()
    if not aliases_path:
        raise ValueError("TELEGRAM_HA_ALIASES_PATH cannot be empty")

    followup_script_entity = os.getenv(
        "TELEGRAM_HA_CLIMATE_FOLLOWUP_SCRIPT",
        "script.architect_schedule_climate_followup",
    ).strip().lower()
    if not followup_script_entity.startswith("script."):
        raise ValueError("TELEGRAM_HA_CLIMATE_FOLLOWUP_SCRIPT must be a script.* entity_id")

    solar_sensor_entity = os.getenv("TELEGRAM_HA_SOLAR_SENSOR_ENTITY", "").strip().lower()
    solar_excess_threshold_watts = _parse_float(
        os.getenv("TELEGRAM_HA_SOLAR_EXCESS_THRESHOLD_W", "0"),
        "TELEGRAM_HA_SOLAR_EXCESS_THRESHOLD_W",
    )

    return HAConfig(
        base_url=base_url,
        token=token,
        approval_ttl_seconds=approval_ttl_seconds,
        temp_min_c=temp_min_c,
        temp_max_c=temp_max_c,
        allowed_domains=allowed_domains,
        allowed_entities=allowed_entities,
        aliases_path=aliases_path,
        followup_script_entity=followup_script_entity,
        solar_sensor_entity=solar_sensor_entity,
        solar_excess_threshold_watts=solar_excess_threshold_watts,
    )


def load_alias_map(path: str) -> Dict[str, str]:
    alias_map: Dict[str, str] = {}
    if not path:
        return alias_map
    if not os.path.exists(path):
        return alias_map

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - guardrail
        raise HAControlError(f"Failed to load alias map {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise HAControlError(f"Alias map {path} must be a JSON object.")

    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        k = key.strip().lower()
        v = value.strip().lower()
        if k and v:
            alias_map[k] = v
    return alias_map


def parse_approval_command(text: str) -> Optional[Tuple[str, Optional[str]]]:
    match = re.match(r"^\s*(approve|cancel)\b(?:\s+.*)?$", text, flags=re.IGNORECASE)
    if not match:
        return None
    action = match.group(1).lower()
    return action, None


def _parse_control_intent(text: str) -> Optional[Dict[str, object]]:
    cleaned = " ".join(text.strip().split()).rstrip(".!?")
    if not cleaned:
        return None

    # Normalize common conversational phrasing.
    cleaned = re.sub(r"^(?:please|pls|kindly)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:can|could|would)\s+you\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bswitch\s+on\b", "turn on", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bswitch\s+off\b", "turn off", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bpower\s+on\b", "turn on", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bpower\s+off\b", "turn off", cleaned, flags=re.IGNORECASE)
    cleaned = " ".join(cleaned.split())

    # set X to 24 [degrees] [and in 3 hours change to 26]
    set_to_temp = re.match(
        r"^set (?:the )?(?P<target>.+?) to (?P<temp_now>\d+(?:\.\d+)?)"
        r"(?:\s*(?:degrees?|c|celsius))?"
        r"(?P<tail>.*)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if set_to_temp:
        tail = set_to_temp.group("tail").strip()
        cleaned = (
            f"turn on {set_to_temp.group('target').strip()} to "
            f"{set_to_temp.group('temp_now')} degrees"
        )
        if tail:
            cleaned = f"{cleaned} {tail}"

    # set X on cool mode to 24 [degrees]
    set_mode_to_temp = re.match(
        r"^set (?:the )?(?P<target>.+?) (?:on|in) (?P<mode>cool|heat|dry|fan|auto) mode"
        r"(?: to)? (?P<temp_now>\d+(?:\.\d+)?)"
        r"(?:\s*(?:degrees?|c|celsius))?"
        r"(?P<tail>.*)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if set_mode_to_temp:
        tail = set_mode_to_temp.group("tail").strip()
        cleaned = (
            f"turn on {set_mode_to_temp.group('target').strip()} on "
            f"{set_mode_to_temp.group('mode').lower()} mode "
            f"{set_mode_to_temp.group('temp_now')} degrees"
        )
        if tail:
            cleaned = f"{cleaned} {tail}"

    # turn off X if we don't have excess solar power
    conditional = re.match(
        r"^turn off (?P<target>.+?) if (?:we )?(?:do not|don't|dont) have excess solar power$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if conditional:
        return {
            "kind": "conditional_turn_off_no_excess_solar",
            "target": conditional.group("target").strip(),
        }

    # turn on X on cool mode 23 [degrees] for next 5 hrs and then change it to 25 [degrees]
    climate_mode_first = re.match(
        r"^turn on (?:the )?(?P<target>.+?) (?:on|in) (?P<mode>cool|heat|dry|fan|auto) mode"
        r"(?: to)? (?P<temp_now>\d+(?:\.\d+)?)(?:\s*(?:degrees?|c|celsius))?"
        r"(?: for (?:next )?(?P<hours>\d+(?:\.\d+)?)\s*(?:hours?|hrs?|hr))?"
        r"(?: and then (?:change|set)(?: it)? to (?P<temp_later>\d+(?:\.\d+)?)"
        r"(?:\s*(?:degrees?|c|celsius))?)?$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if climate_mode_first:
        return {
            "kind": "climate_set",
            "target": climate_mode_first.group("target").strip(),
            "mode": climate_mode_first.group("mode").lower(),
            "temp_now": float(climate_mode_first.group("temp_now")),
            "hours": float(climate_mode_first.group("hours")) if climate_mode_first.group("hours") else None,
            "temp_later": float(climate_mode_first.group("temp_later")) if climate_mode_first.group("temp_later") else None,
        }

    # turn on X to 25 [degrees] and in 3 hours change it to 27 [degrees]
    climate_to_temp = re.match(
        r"^turn on (?:the )?(?P<target>.+?)(?: (?:on|in) (?P<mode>cool|heat|dry|fan|auto) mode)? to "
        r"(?P<temp_now>\d+(?:\.\d+)?)(?:\s*(?:degrees?|c|celsius))?"
        r"(?: and in (?P<hours>\d+(?:\.\d+)?)\s*(?:hours?|hrs?|hr) "
        r"(?:change|set)(?: it)? to (?P<temp_later>\d+(?:\.\d+)?)"
        r"(?:\s*(?:degrees?|c|celsius))?)?$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if climate_to_temp:
        return {
            "kind": "climate_set",
            "target": climate_to_temp.group("target").strip(),
            "mode": climate_to_temp.group("mode").lower() if climate_to_temp.group("mode") else None,
            "temp_now": float(climate_to_temp.group("temp_now")),
            "hours": float(climate_to_temp.group("hours")) if climate_to_temp.group("hours") else None,
            "temp_later": float(climate_to_temp.group("temp_later")) if climate_to_temp.group("temp_later") else None,
        }

    simple = re.match(
        r"^turn (?P<verb>on|off) (?:the )?(?P<target>.+)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if simple:
        return {
            "kind": "entity_turn_on" if simple.group("verb").lower() == "on" else "entity_turn_off",
            "target": simple.group("target").strip(),
        }

    return None


def _entity_name(entity: Dict[str, object]) -> str:
    attrs = entity.get("attributes")
    if isinstance(attrs, dict):
        friendly = attrs.get("friendly_name")
        if isinstance(friendly, str) and friendly.strip():
            return friendly.strip()
    entity_id = entity.get("entity_id")
    if isinstance(entity_id, str):
        return entity_id
    return "unknown"


def _build_entity_index(states: Sequence[Dict[str, object]]) -> Tuple[Dict[str, Dict[str, object]], Dict[str, Set[str]]]:
    by_id: Dict[str, Dict[str, object]] = {}
    candidate_map: Dict[str, Set[str]] = {}

    for entity in states:
        entity_id = entity.get("entity_id")
        if not isinstance(entity_id, str) or "." not in entity_id:
            continue
        eid = entity_id.strip().lower()
        by_id[eid] = entity

        candidates = {eid, eid.replace("_", " ")}
        obj = eid.split(".", 1)[1]
        candidates.add(obj)
        candidates.add(obj.replace("_", " "))

        attrs = entity.get("attributes")
        if isinstance(attrs, dict):
            friendly = attrs.get("friendly_name")
            if isinstance(friendly, str) and friendly.strip():
                candidates.add(friendly.strip().lower())

        for candidate in candidates:
            normalized = _normalize_alias(candidate)
            if not normalized:
                continue
            candidate_map.setdefault(normalized, set()).add(eid)

    return by_id, candidate_map


def _resolve_entity_id(
    target: str,
    states: Sequence[Dict[str, object]],
    alias_map: Dict[str, str],
) -> Tuple[str, Dict[str, object]]:
    by_id, candidate_map = _build_entity_index(states)
    target_clean = target.strip().lower()
    if not target_clean:
        raise HAControlError("Missing target entity name.")

    if "." in target_clean and target_clean in by_id:
        return target_clean, by_id[target_clean]

    if target_clean in alias_map:
        alias_entity = alias_map[target_clean].lower()
        if alias_entity in by_id:
            return alias_entity, by_id[alias_entity]
        raise HAControlError(f"Alias '{target}' maps to unknown entity '{alias_entity}'.")

    normalized = _normalize_alias(target_clean)
    if normalized in alias_map:
        alias_entity = alias_map[normalized].lower()
        if alias_entity in by_id:
            return alias_entity, by_id[alias_entity]

    direct = candidate_map.get(normalized, set())
    if len(direct) == 1:
        entity_id = sorted(direct)[0]
        return entity_id, by_id[entity_id]

    partial_matches: Set[str] = set()
    for key, values in candidate_map.items():
        if normalized in key or key in normalized:
            partial_matches.update(values)

    if len(partial_matches) == 1:
        entity_id = sorted(partial_matches)[0]
        return entity_id, by_id[entity_id]

    if not partial_matches and not direct:
        raise HAControlError(f"Could not find a Home Assistant entity matching '{target}'.")

    candidates = sorted(partial_matches or direct)
    preview = ", ".join(candidates[:5])
    raise HAControlError(
        f"Target '{target}' is ambiguous. Matches: {preview}. Please use a more specific name or entity_id."
    )


def _ensure_allowed(entity_id: str, config: HAConfig) -> None:
    domain = entity_id.split(".", 1)[0]
    if domain not in config.allowed_domains:
        raise HAControlError(f"Entity '{entity_id}' is not in allowed domains: {sorted(config.allowed_domains)}")
    if config.allowed_entities and entity_id not in config.allowed_entities:
        raise HAControlError("Entity is not in TELEGRAM_HA_ALLOWED_ENTITIES allowlist.")


def _validate_temperature(temp_c: float, config: HAConfig) -> None:
    if temp_c < config.temp_min_c or temp_c > config.temp_max_c:
        raise HAControlError(
            f"Temperature {temp_c:g}C is out of range {config.temp_min_c:g}-{config.temp_max_c:g}C."
        )


def _parse_numeric_sensor_state(raw: str) -> Optional[float]:
    value = (raw or "").strip().lower()
    if not value or value in {"unknown", "unavailable", "none"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def plan_action_from_text(
    text: str,
    client: HomeAssistantClient,
    config: HAConfig,
) -> Optional[Dict[str, object]]:
    intent = _parse_control_intent(text)
    if intent is None:
        return None

    alias_map = load_alias_map(config.aliases_path)
    states = client.get_states()

    target = intent.get("target")
    if not isinstance(target, str):
        raise HAControlError("Invalid target in parsed intent.")

    entity_id, entity_state = _resolve_entity_id(target, states, alias_map)
    _ensure_allowed(entity_id, config)

    kind = intent["kind"]
    entity_display = _entity_name(entity_state)

    if kind == "entity_turn_off":
        return {
            "kind": "entity_turn_off",
            "entity_id": entity_id,
            "summary": f"Turn OFF {entity_display} ({entity_id}).",
        }

    if kind == "entity_turn_on":
        return {
            "kind": "entity_turn_on",
            "entity_id": entity_id,
            "summary": f"Turn ON {entity_display} ({entity_id}).",
        }

    if kind == "conditional_turn_off_no_excess_solar":
        if not config.solar_sensor_entity:
            raise HAControlError("TELEGRAM_HA_SOLAR_SENSOR_ENTITY is required for excess-solar condition commands.")
        solar_threshold = config.solar_excess_threshold_watts
        return {
            "kind": "conditional_turn_off_no_excess_solar",
            "entity_id": entity_id,
            "solar_sensor_entity": config.solar_sensor_entity,
            "solar_threshold_w": solar_threshold,
            "summary": (
                f"If solar export is NOT above {solar_threshold:g}W, turn OFF "
                f"{entity_display} ({entity_id})."
            ),
        }

    if kind == "climate_set":
        if not entity_id.startswith("climate."):
            raise HAControlError(f"'{entity_id}' is not a climate entity.")
        temp_now = float(intent["temp_now"])
        _validate_temperature(temp_now, config)

        mode = intent.get("mode")
        if mode is not None and not isinstance(mode, str):
            mode = None

        followup_hours = intent.get("hours")
        followup_temp = intent.get("temp_later")
        if followup_temp is not None and followup_hours is None:
            raise HAControlError("Follow-up temperature requested but follow-up time is missing.")
        if followup_hours is not None and followup_temp is None:
            raise HAControlError("Follow-up time requested but follow-up temperature is missing.")
        if followup_hours is not None and float(followup_hours) <= 0:
            raise HAControlError("Follow-up hours must be greater than zero.")

        if followup_temp is not None:
            followup_temp = float(followup_temp)
            _validate_temperature(followup_temp, config)

        summary = f"Set {entity_display} ({entity_id}) to {temp_now:g}C"
        if mode:
            summary += f" in {mode} mode"
        if followup_hours is not None and followup_temp is not None:
            summary += f", then set to {followup_temp:g}C in {float(followup_hours):g} hour(s)"

        return {
            "kind": "climate_set",
            "entity_id": entity_id,
            "hvac_mode": mode,
            "temperature_now": temp_now,
            "followup_hours": float(followup_hours) if followup_hours is not None else None,
            "followup_temperature": followup_temp,
            "summary": summary + ".",
        }

    return None


def execute_action(
    action: Dict[str, object],
    client: HomeAssistantClient,
    config: HAConfig,
) -> str:
    kind = action.get("kind")
    if not isinstance(kind, str):
        raise HAControlError("Invalid action payload.")

    entity_id = action.get("entity_id")
    if not isinstance(entity_id, str):
        raise HAControlError("Action missing entity_id.")

    _ensure_allowed(entity_id, config)
    domain = entity_id.split(".", 1)[0]

    if kind == "entity_turn_off":
        client.call_service(domain, "turn_off", {"entity_id": entity_id})
        return f"Executed: turned OFF {entity_id}."

    if kind == "entity_turn_on":
        client.call_service(domain, "turn_on", {"entity_id": entity_id})
        return f"Executed: turned ON {entity_id}."

    if kind == "conditional_turn_off_no_excess_solar":
        sensor_id = action.get("solar_sensor_entity")
        threshold = action.get("solar_threshold_w")
        if not isinstance(sensor_id, str) or not sensor_id:
            raise HAControlError("Action missing solar_sensor_entity.")
        threshold_w = float(threshold) if isinstance(threshold, (int, float)) else config.solar_excess_threshold_watts

        sensor_state = client.get_state(sensor_id)
        if not sensor_state:
            raise HAControlError(f"Solar sensor not found: {sensor_id}")

        sensor_value = _parse_numeric_sensor_state(str(sensor_state.get("state", "")))
        if sensor_value is None:
            raise HAControlError(f"Solar sensor state is not numeric: {sensor_id}")

        if sensor_value > threshold_w:
            return (
                f"Skipped: solar export is {sensor_value:g}W (above threshold {threshold_w:g}W). "
                f"No change applied to {entity_id}."
            )

        client.call_service(domain, "turn_off", {"entity_id": entity_id})
        return (
            f"Executed: solar export is {sensor_value:g}W (not above {threshold_w:g}W), "
            f"turned OFF {entity_id}."
        )

    if kind == "climate_set":
        if not entity_id.startswith("climate."):
            raise HAControlError("Climate action entity_id must be climate.*")

        hvac_mode = action.get("hvac_mode")
        if isinstance(hvac_mode, str) and hvac_mode:
            client.call_service(
                "climate",
                "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": hvac_mode},
            )

        temp_now = action.get("temperature_now")
        if not isinstance(temp_now, (int, float)):
            raise HAControlError("Climate action missing temperature_now.")
        _validate_temperature(float(temp_now), config)
        client.call_service(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": float(temp_now)},
        )

        followup_hours = action.get("followup_hours")
        followup_temperature = action.get("followup_temperature")
        if isinstance(followup_hours, (int, float)) and isinstance(followup_temperature, (int, float)):
            _validate_temperature(float(followup_temperature), config)
            client.call_service(
                "script",
                "turn_on",
                {
                    "entity_id": config.followup_script_entity,
                    "variables": {
                        "entity_id": entity_id,
                        "temperature": float(followup_temperature),
                        "delay_hours": float(followup_hours),
                    },
                },
            )
            return (
                f"Executed: set {entity_id} to {float(temp_now):g}C"
                + (f" with mode {hvac_mode}" if isinstance(hvac_mode, str) and hvac_mode else "")
                + (
                    f"; scheduled {float(followup_temperature):g}C in {float(followup_hours):g} hour(s) "
                    f"via {config.followup_script_entity}."
                )
            )

        return (
            f"Executed: set {entity_id} to {float(temp_now):g}C"
            + (f" with mode {hvac_mode}." if isinstance(hvac_mode, str) and hvac_mode else ".")
        )

    raise HAControlError(f"Unsupported action kind: {kind}")


def build_pending_message(summary: str, ttl_seconds: int) -> str:
    minutes = max(1, int(round(ttl_seconds / 60.0)))
    return (
        "HA action ready.\n"
        f"{summary}\n\n"
        "Reply APPROVE to execute, or CANCEL to abort. "
        f"(expires in ~{minutes} min)"
    )


def is_ha_network_error(exc: Exception) -> bool:
    return isinstance(exc, (HTTPError, URLError, TimeoutError))


def now_ts() -> float:
    return time.time()
