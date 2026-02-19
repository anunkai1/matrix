#!/usr/bin/env python3
"""Home Assistant control helpers for the Telegram bridge."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


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
    match_min_score: float
    match_ambiguity_gap: float


@dataclass
class HAScheduleStep:
    step_id: str
    run_at_ts: float
    action: Dict[str, object]
    summary: str


@dataclass
class HASchedulePlan:
    summary: str
    steps: List[HAScheduleStep]
    entity_ids: Set[str]
    is_complex: bool


DELAY_RE = re.compile(
    r"\b(in|after)\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?|minute|hour)\b"
)
DURATION_RE = re.compile(
    r"\bfor\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?|minute|hour)\b"
)
AT_TIME_RE = re.compile(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b")
SEGMENT_SPLIT_RE = re.compile(r"\b(?:and\s+then|then)\b")

STATUS_QUERY_PHRASES = (
    "whats on",
    "what is on",
    "whats running",
    "what is running",
    "whats active",
    "what is active",
    "what is happening",
    "check whats on",
    "check what is on",
    "show whats on",
    "show what is on",
)

STATUS_SUPPORTED_DOMAINS = {
    "alarm_control_panel",
    "climate",
    "cover",
    "fan",
    "humidifier",
    "input_boolean",
    "light",
    "lock",
    "media_player",
    "script",
    "switch",
    "vacuum",
    "water_heater",
}


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

    match_min_score = _parse_float(
        os.getenv("TELEGRAM_HA_MATCH_MIN_SCORE", "0.46"),
        "TELEGRAM_HA_MATCH_MIN_SCORE",
    )
    if match_min_score <= 0 or match_min_score > 1:
        raise ValueError("TELEGRAM_HA_MATCH_MIN_SCORE must be in (0, 1]")

    match_ambiguity_gap = _parse_float(
        os.getenv("TELEGRAM_HA_MATCH_AMBIGUITY_GAP", "0.05"),
        "TELEGRAM_HA_MATCH_AMBIGUITY_GAP",
    )
    if match_ambiguity_gap < 0 or match_ambiguity_gap > 1:
        raise ValueError("TELEGRAM_HA_MATCH_AMBIGUITY_GAP must be in [0, 1]")

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
        match_min_score=match_min_score,
        match_ambiguity_gap=match_ambiguity_gap,
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
    parts = text.strip().split()
    if len(parts) != 1:
        return None
    head = parts[0].lower()
    if head not in {"approve", "cancel"}:
        return None
    return head, None


def _canonical_token(token: str) -> str:
    mapping = {
        "ac": "aircon",
        "a.c": "aircon",
        "airconditioner": "aircon",
        "conditioner": "aircon",
        "cooling": "cool",
        "heating": "heat",
        "hit": "heat",
        "dryer": "dry",
        "automatic": "auto",
        "rm": "room",
        "hrs": "hours",
        "hr": "hour",
        "degrees": "degree",
        "deg": "degree",
        "celcius": "celsius",
        "dont": "dont",
    }
    return mapping.get(token, token)


def _tokenize_text(text: str) -> List[str]:
    lowered = text.lower()
    for source, replacement in (
        ("a/c", "ac"),
        ("air conditioner", "aircon"),
        ("air con", "aircon"),
    ):
        lowered = lowered.replace(source, replacement)
    lowered = lowered.replace("'", "")

    cleaned_chars: List[str] = []
    for ch in lowered:
        if ch.isalnum() or ch in {" ", ".", "_"}:
            cleaned_chars.append(ch)
        else:
            cleaned_chars.append(" ")

    raw_tokens = [part for part in "".join(cleaned_chars).split() if part]

    tokens: List[str] = []
    i = 0
    while i < len(raw_tokens):
        token = _canonical_token(raw_tokens[i])
        nxt = _canonical_token(raw_tokens[i + 1]) if i + 1 < len(raw_tokens) else ""

        # Common voice-transcription variant for "AC".
        if token == "i" and nxt == "see":
            tokens.append("aircon")
            i += 2
            continue

        if token in {"switch", "power"} and nxt in {"on", "off"}:
            tokens.extend(["turn", nxt])
            i += 2
            continue
        tokens.append(token)
        i += 1

    return tokens


def _normalize_alias(value: str) -> str:
    tokens = _tokenize_text(value)
    chars: List[str] = []
    for token in tokens:
        for ch in token:
            if ch.isalnum():
                chars.append(ch)
    return "".join(chars)


def _parse_number_token(token: str) -> Optional[float]:
    try:
        return float(token)
    except ValueError:
        return None


def _parse_control_intent(text: str) -> Optional[Dict[str, object]]:
    tokens = _tokenize_text(text)
    if not tokens:
        return None

    polite_prefixes = {"please", "pls", "kindly"}
    while tokens and tokens[0] in polite_prefixes:
        tokens = tokens[1:]

    if len(tokens) >= 2 and tokens[0] in {"can", "could", "would"} and tokens[1] == "you":
        tokens = tokens[2:]

    # Ignore filler lead-ins frequently seen in speech or dictation.
    while tokens and tokens[0] in {"to", "your", "normal", "just", "simply", "now"}:
        tokens = tokens[1:]

    if not tokens:
        return None

    turn_idx = -1
    turn_state = ""
    for i in range(len(tokens) - 1):
        if tokens[i] == "turn" and tokens[i + 1] in {"on", "off"}:
            turn_idx = i
            turn_state = tokens[i + 1]
            break

    set_idx = -1
    for i, token in enumerate(tokens):
        if token in {"set", "change"}:
            set_idx = i
            break

    def extract_target(start_idx: int, climate_hint: bool, stop_at_if: bool = False) -> str:
        idx = start_idx
        while idx < len(tokens) and tokens[idx] in {"the", "my", "our"}:
            idx += 1

        stop_words = {"and", "then", "for"}
        if stop_at_if:
            stop_words.add("if")
        if climate_hint:
            stop_words.update({"to", "on", "in", "mode"})

        out: List[str] = []
        while idx < len(tokens):
            token = tokens[idx]
            if token in stop_words:
                break
            out.append(token)
            idx += 1
        return " ".join(out).strip()

    mode = None
    hvac_modes = {"cool", "heat", "dry", "fan", "auto"}
    for token in tokens:
        if token in hvac_modes:
            mode = token
            break

    hour_units = {"hour", "hours"}

    followup_hours: Optional[float] = None
    for i in range(len(tokens) - 2):
        if tokens[i] == "in":
            val = _parse_number_token(tokens[i + 1])
            if val is not None and tokens[i + 2] in hour_units:
                followup_hours = val
                break
    if followup_hours is None:
        for i in range(len(tokens) - 2):
            if tokens[i] == "for":
                j = i + 1
                if j < len(tokens) and tokens[j] == "next":
                    j += 1
                if j + 1 < len(tokens):
                    val = _parse_number_token(tokens[j])
                    if val is not None and tokens[j + 1] in hour_units:
                        followup_hours = val
                        break

    temps: List[Tuple[int, float]] = []
    for i, token in enumerate(tokens):
        value = _parse_number_token(token)
        if value is None:
            continue
        if i + 1 < len(tokens) and tokens[i + 1] in hour_units:
            continue
        if not (8 <= value <= 40):
            continue
        temps.append((i, value))

    main_temp = temps[0][1] if temps else None
    followup_temp: Optional[float] = None
    if len(temps) >= 2:
        followup_temp = temps[1][1]

    if turn_state == "off":
        has_excess = all(word in tokens for word in ("excess", "solar", "power"))
        has_negative = "dont" in tokens or ("do" in tokens and "not" in tokens)
        if has_excess and has_negative and "if" in tokens:
            target = extract_target(turn_idx + 2, climate_hint=False, stop_at_if=True)
            if not target:
                return None
            return {
                "kind": "conditional_turn_off_no_excess_solar",
                "target": target,
            }

    climate_candidate = False
    if turn_state == "on" and (main_temp is not None or mode is not None):
        climate_candidate = True
    if set_idx >= 0 and (main_temp is not None or mode is not None):
        climate_candidate = True
    if turn_state == "" and set_idx < 0 and (main_temp is not None or mode is not None):
        if "aircon" in tokens:
            climate_candidate = True

    if climate_candidate:
        if main_temp is None:
            return None

        if turn_state == "on":
            target = extract_target(turn_idx + 2, climate_hint=True)
        elif set_idx >= 0:
            target = extract_target(set_idx + 1, climate_hint=True)
        else:
            inferred_start = 0
            while inferred_start < len(tokens) and tokens[inferred_start] in {"to", "in", "on", "at"}:
                inferred_start += 1
            target = extract_target(inferred_start, climate_hint=True)

        if not target:
            return None

        if followup_hours is None:
            followup_temp = None

        return {
            "kind": "climate_set",
            "target": target,
            "mode": mode,
            "temp_now": float(main_temp),
            "hours": float(followup_hours) if followup_hours is not None else None,
            "temp_later": float(followup_temp) if followup_temp is not None else None,
        }

    if turn_state in {"on", "off"}:
        target = extract_target(turn_idx + 2, climate_hint=False, stop_at_if=True)
        if not target:
            return None
        return {
            "kind": "entity_turn_on" if turn_state == "on" else "entity_turn_off",
            "target": target,
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


def _entity_candidate_labels(entity: Dict[str, object]) -> Set[str]:
    entity_id = str(entity.get("entity_id", "")).strip().lower()
    out: Set[str] = set()
    if entity_id:
        out.add(entity_id)
        out.add(entity_id.replace("_", " "))
        if "." in entity_id:
            obj = entity_id.split(".", 1)[1]
            out.add(obj)
            out.add(obj.replace("_", " "))

    attrs = entity.get("attributes")
    if isinstance(attrs, dict):
        for key in ("friendly_name", "name", "area", "area_name", "room"):
            value = attrs.get(key)
            if isinstance(value, str) and value.strip():
                out.add(value.strip().lower())

    return {label for label in out if label}


def _build_entity_index(states: Sequence[Dict[str, object]]) -> Tuple[Dict[str, Dict[str, object]], Dict[str, List[str]]]:
    by_id: Dict[str, Dict[str, object]] = {}
    labels_by_id: Dict[str, List[str]] = {}

    for entity in states:
        entity_id = entity.get("entity_id")
        if not isinstance(entity_id, str) or "." not in entity_id:
            continue

        eid = entity_id.strip().lower()
        by_id[eid] = entity
        labels = sorted(_entity_candidate_labels(entity))
        labels_by_id[eid] = labels

    return by_id, labels_by_id


def _score_label_match(target: str, label: str) -> float:
    target_tokens = _tokenize_text(target)
    label_tokens = _tokenize_text(label)

    if not target_tokens or not label_tokens:
        return 0.0

    target_norm = " ".join(target_tokens)
    label_norm = " ".join(label_tokens)

    seq_ratio = SequenceMatcher(None, target_norm, label_norm).ratio()

    target_set = set(target_tokens)
    label_set = set(label_tokens)
    overlap = len(target_set.intersection(label_set)) / float(max(len(target_set), len(label_set)))

    containment = 1.0 if target_norm in label_norm or label_norm in target_norm else 0.0

    return 0.55 * seq_ratio + 0.35 * overlap + 0.10 * containment


def _resolve_entity_id(
    target: str,
    states: Sequence[Dict[str, object]],
    alias_map: Dict[str, str],
    config: HAConfig,
    preferred_domain: Optional[str] = None,
) -> Tuple[str, Dict[str, object]]:
    by_id, labels_by_id = _build_entity_index(states)
    target_clean = target.strip().lower()
    if not target_clean:
        raise HAControlError("Missing target entity name.")

    if "." in target_clean and target_clean in by_id:
        return target_clean, by_id[target_clean]

    alias_raw = {k.strip().lower(): v.strip().lower() for k, v in alias_map.items() if k.strip() and v.strip()}
    alias_norm = {_normalize_alias(k): v for k, v in alias_raw.items()}

    if target_clean in alias_raw:
        alias_entity = alias_raw[target_clean]
        if alias_entity in by_id:
            return alias_entity, by_id[alias_entity]
        raise HAControlError(f"Alias '{target}' maps to unknown entity '{alias_entity}'.")

    norm_target = _normalize_alias(target_clean)
    if norm_target in alias_norm:
        alias_entity = alias_norm[norm_target]
        if alias_entity in by_id:
            return alias_entity, by_id[alias_entity]
        raise HAControlError(f"Alias '{target}' maps to unknown entity '{alias_entity}'.")

    scores: List[Tuple[float, str]] = []
    hint_tokens = set(_tokenize_text(target_clean))

    for entity_id, labels in labels_by_id.items():
        domain = entity_id.split(".", 1)[0]
        if domain not in config.allowed_domains:
            continue
        if config.allowed_entities and entity_id not in config.allowed_entities:
            continue

        best_score = 0.0
        for label in labels:
            score = _score_label_match(target_clean, label)
            if score > best_score:
                best_score = score

        if preferred_domain and domain == preferred_domain:
            best_score += 0.08
        if "aircon" in hint_tokens and domain == "climate":
            best_score += 0.05

        scores.append((best_score, entity_id))

    if not scores:
        raise HAControlError(
            f"No allowed Home Assistant entity matched '{target}'. "
            "Check TELEGRAM_HA_ALLOWED_DOMAINS/TELEGRAM_HA_ALLOWED_ENTITIES."
        )

    scores.sort(key=lambda item: item[0], reverse=True)
    top_score, top_entity_id = scores[0]

    if top_score < config.match_min_score:
        suggestions = []
        for _, candidate_id in scores[:5]:
            suggestions.append(f"{_entity_name(by_id[candidate_id])} ({candidate_id})")
        preview = ", ".join(suggestions)
        raise HAControlError(
            f"Could not confidently match '{target}'. Closest entities: {preview}."
        )

    if len(scores) > 1:
        second_score, second_entity_id = scores[1]
        if top_score - second_score < config.match_ambiguity_gap:
            options = [top_entity_id, second_entity_id]
            preview = ", ".join(
                f"{_entity_name(by_id[cid])} ({cid})" for cid in options
            )
            raise HAControlError(
                f"Target '{target}' is ambiguous. Closest matches: {preview}. Please be more specific."
            )

    return top_entity_id, by_id[top_entity_id]


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


def _build_action_from_intent(
    intent: Dict[str, object],
    states: Sequence[Dict[str, object]],
    alias_map: Dict[str, str],
    config: HAConfig,
) -> Dict[str, object]:
    target = intent.get("target")
    if not isinstance(target, str):
        raise HAControlError("Invalid target in parsed intent.")

    preferred_domain = None
    if intent.get("kind") == "climate_set":
        preferred_domain = "climate"

    entity_id, entity_state = _resolve_entity_id(
        target,
        states,
        alias_map,
        config,
        preferred_domain=preferred_domain,
    )
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

    raise HAControlError(f"Unsupported intent kind: {kind}")


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
    return _build_action_from_intent(intent, states, alias_map, config)


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


def _duration_seconds(value_raw: str, unit_raw: str) -> float:
    value = float(value_raw)
    if value <= 0:
        raise HAControlError("Duration must be greater than zero.")
    unit = unit_raw.strip().lower()
    if unit.startswith("hour") or unit.startswith("hr"):
        return value * 3600.0
    return value * 60.0


def _next_absolute_ts(
    now_ts_value: float,
    timezone_name: str,
    hour_raw: str,
    minute_raw: Optional[str],
    ampm_raw: Optional[str],
) -> float:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception as exc:
        raise HAControlError(f"Invalid timezone: {timezone_name}") from exc

    now_local = datetime.fromtimestamp(now_ts_value, tz=tz)

    hour = int(hour_raw)
    minute = int(minute_raw) if minute_raw else 0
    ampm = (ampm_raw or "").strip().lower()

    if ampm:
        if hour < 1 or hour > 12:
            raise HAControlError("12-hour clock times must use hour in 1-12.")
        if ampm == "pm" and hour != 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
    elif hour > 23 or minute > 59:
        raise HAControlError("Invalid 24-hour time value.")

    scheduled = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if scheduled <= now_local:
        scheduled = scheduled + timedelta(days=1)
    return scheduled.astimezone(timezone.utc).timestamp()


def _format_run_at(run_at_ts: float, timezone_name: str) -> str:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = timezone.utc
    dt_local = datetime.fromtimestamp(run_at_ts, tz=tz)
    return dt_local.strftime("%Y-%m-%d %H:%M")


def _looks_like_ha_schedule_text(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    return bool(
        re.search(
            r"\b(turn|set|change|switch|aircon|heater|light|fan)\b",
            lowered,
        )
    )


def _normalize_turn_order(text: str) -> str:
    lowered = text.strip()
    if not lowered:
        return lowered
    if re.search(r"\bturn\s+(on|off)\b", lowered):
        return lowered
    match = re.search(r"\bturn\s+(.+?)\s+(on|off)\b", lowered)
    if not match:
        return lowered
    target = match.group(1).strip()
    state = match.group(2).strip()
    prefix = lowered[: match.start()]
    suffix = lowered[match.end() :]
    return f"{prefix}turn {state} {target}{suffix}".strip()


def _sanitize_segment(
    segment: str,
    last_target_hint: Optional[str],
) -> str:
    cleaned = " ".join(segment.strip().split())
    if not cleaned:
        return ""
    cleaned = re.sub(r"^\b(?:and|then|after that)\b\s*", "", cleaned, flags=re.IGNORECASE).strip()

    if last_target_hint:
        cleaned = re.sub(
            r"\b(it|that|this)\b",
            last_target_hint,
            cleaned,
            count=1,
            flags=re.IGNORECASE,
        )
        lowered = cleaned.lower()
        if lowered.startswith("change temperature to "):
            cleaned = f"set {last_target_hint} to {cleaned[len('change temperature to '):].strip()}"
        elif lowered.startswith("change to "):
            cleaned = f"set {last_target_hint} to {cleaned[len('change to '):].strip()}"

    return _normalize_turn_order(cleaned)


def parse_schedule_plan_from_text(
    text: str,
    client: HomeAssistantClient,
    config: HAConfig,
    timezone_name: str,
    now_ts_value: Optional[float] = None,
) -> Optional[HASchedulePlan]:
    source = (text or "").strip()
    if not _looks_like_ha_schedule_text(source):
        return None

    now_value = now_ts() if now_ts_value is None else float(now_ts_value)
    segments = [part.strip() for part in SEGMENT_SPLIT_RE.split(source) if part.strip()]
    if not segments:
        return None

    alias_map = load_alias_map(config.aliases_path)
    states: Optional[List[Dict[str, object]]] = None
    cursor_ts = now_value
    last_target_hint: Optional[str] = None

    steps: List[HAScheduleStep] = []
    entity_ids: Set[str] = set()

    for index, raw_segment in enumerate(segments, start=1):
        segment = raw_segment
        run_at_ts = cursor_ts if index > 1 else now_value

        delay_match = DELAY_RE.search(segment)
        if delay_match:
            seconds = _duration_seconds(delay_match.group(2), delay_match.group(3))
            anchor = delay_match.group(1).lower()
            if anchor == "after":
                run_at_ts = cursor_ts + seconds
            else:
                run_at_ts = now_value + seconds
            segment = (segment[: delay_match.start()] + " " + segment[delay_match.end() :]).strip()

        at_match = AT_TIME_RE.search(segment)
        if at_match:
            run_at_ts = _next_absolute_ts(
                now_value,
                timezone_name,
                at_match.group(1),
                at_match.group(2),
                at_match.group(3),
            )
            segment = (segment[: at_match.start()] + " " + segment[at_match.end() :]).strip()

        duration_seconds = 0.0
        duration_match = DURATION_RE.search(segment)
        if duration_match:
            duration_seconds = _duration_seconds(duration_match.group(1), duration_match.group(2))
            segment = (segment[: duration_match.start()] + " " + segment[duration_match.end() :]).strip()

        normalized = _sanitize_segment(segment, last_target_hint)
        intent = _parse_control_intent(normalized)
        if intent is None:
            if index == 1:
                return None
            raise HAControlError(f"Could not parse HA segment: {raw_segment!r}")

        if states is None:
            states = client.get_states()
        action = _build_action_from_intent(intent, states, alias_map, config)
        entity_id = action.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id:
            raise HAControlError("Resolved HA action missing entity_id.")

        last_target_hint = entity_id
        entity_ids.add(entity_id)
        summary = action.get("summary", f"Execute {action.get('kind')} on {entity_id}.")
        if not isinstance(summary, str):
            summary = f"Execute {action.get('kind')} on {entity_id}."

        steps.append(
            HAScheduleStep(
                step_id=str(uuid.uuid4()),
                run_at_ts=run_at_ts,
                action=action,
                summary=summary,
            )
        )

        if duration_seconds > 0 and action.get("kind") in {"entity_turn_on", "climate_set"}:
            off_action: Dict[str, object] = {
                "kind": "entity_turn_off",
                "entity_id": entity_id,
                "summary": f"Turn OFF {entity_id}.",
            }
            off_run_ts = run_at_ts + duration_seconds
            steps.append(
                HAScheduleStep(
                    step_id=str(uuid.uuid4()),
                    run_at_ts=off_run_ts,
                    action=off_action,
                    summary=f"Turn OFF {entity_id}.",
                )
            )

        cursor_ts = run_at_ts

    if not steps:
        return None

    steps.sort(key=lambda item: item.run_at_ts)
    summary_lines: List[str] = []
    for idx, step in enumerate(steps, start=1):
        label = "now" if step.run_at_ts <= now_value + 2 else _format_run_at(step.run_at_ts, timezone_name)
        summary_lines.append(f"{idx}. [{label}] {step.summary}")
    is_complex = len(steps) > 1 or any(step.run_at_ts > now_value + 5 for step in steps)
    return HASchedulePlan(
        summary="HA schedule plan:\n" + "\n".join(summary_lines),
        steps=steps,
        entity_ids=entity_ids,
        is_complex=is_complex,
    )


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


def looks_like_ha_status_query(text: str, allow_implicit: bool = False) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    if parse_approval_command(cleaned):
        return False
    if _parse_control_intent(cleaned) is not None:
        return False

    tokens = _tokenize_text(cleaned)
    if not tokens:
        return False
    token_set = set(tokens)
    normalized = " ".join(tokens)

    explicit_ha_context = "ha" in token_set or ("home" in token_set and "assistant" in token_set)
    if not explicit_ha_context and not allow_implicit:
        return False

    if "status" in token_set:
        return True

    phrase_hit = any(phrase in normalized for phrase in STATUS_QUERY_PHRASES)
    if not phrase_hit:
        return False

    if explicit_ha_context:
        return True

    if "right now" in normalized:
        return True
    if "now" in token_set or "currently" in token_set:
        return True
    return False


def _is_active_entity_state(entity_id: str, state_raw: str, attrs: Dict[str, object]) -> bool:
    state = (state_raw or "").strip().lower()
    if not state or state in {"unknown", "unavailable", "none"}:
        return False

    domain = entity_id.split(".", 1)[0]
    if domain not in STATUS_SUPPORTED_DOMAINS:
        return False

    if domain in {"switch", "light", "input_boolean", "fan", "humidifier", "script"}:
        return state == "on"
    if domain == "cover":
        return state in {"open", "opening", "closing"}
    if domain == "media_player":
        return state in {"on", "playing", "paused", "buffering", "idle"}
    if domain == "vacuum":
        return state in {"cleaning", "returning", "paused", "error"}
    if domain == "lock":
        return state == "unlocked"
    if domain == "alarm_control_panel":
        return state.startswith("armed") or state == "triggered"
    if domain == "water_heater":
        return state != "off"
    if domain == "climate":
        hvac_action = str(attrs.get("hvac_action", "")).strip().lower()
        if hvac_action in {"heating", "cooling", "drying", "fan", "preheating", "defrosting"}:
            return True
        return state in {"heat", "cool", "dry", "fan_only", "auto", "heat_cool", "heating", "cooling"}
    return state == "on"


def summarize_active_ha_entities(
    client: HomeAssistantClient,
    config: HAConfig,
    limit: int = 20,
) -> str:
    states = client.get_states()
    rows: List[Tuple[str, str, str, str, str]] = []

    for entity in states:
        entity_id = entity.get("entity_id")
        if not isinstance(entity_id, str) or "." not in entity_id:
            continue

        eid = entity_id.strip().lower()
        domain = eid.split(".", 1)[0]
        if domain not in config.allowed_domains:
            continue
        if config.allowed_entities and eid not in config.allowed_entities:
            continue

        state_raw = str(entity.get("state", "")).strip()
        attrs = entity.get("attributes")
        attrs_dict = attrs if isinstance(attrs, dict) else {}
        if not _is_active_entity_state(eid, state_raw, attrs_dict):
            continue

        name = _entity_name(entity)
        rows.append((domain, name.lower(), name, eid, state_raw))

    if not rows:
        return "HA status: no allowed entities are currently on/active."

    rows.sort(key=lambda item: (item[0], item[1], item[3]))
    lines = [f"HA status: {len(rows)} allowed entities currently on/active."]
    for _, _, name, eid, state_raw in rows[:limit]:
        lines.append(f"- {name} ({eid}) -> {state_raw}")
    if len(rows) > limit:
        lines.append(f"- ...and {len(rows) - limit} more.")
    return "\n".join(lines)


def looks_like_ha_control_text(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    if parse_approval_command(cleaned):
        return True
    return _parse_control_intent(cleaned) is not None


def run_ha_parser_self_test() -> None:
    cases = [
        (
            "turn on masters AC to cool 24",
            {"kind": "climate_set", "target": "masters aircon", "mode": "cool", "temp_now": 24.0},
        ),
        (
            "please switch on living room aircon to 23",
            {"kind": "climate_set", "target": "living room aircon", "temp_now": 23.0},
        ),
        (
            "turn off water heater",
            {"kind": "entity_turn_off", "target": "water heater"},
        ),
        (
            "Set masters I see to 23 degrees cooling and turn it on",
            {"kind": "climate_set", "target": "masters aircon", "mode": "cool", "temp_now": 23.0},
        ),
        (
            "Turn on Master's AC to hit mode 23",
            {"kind": "climate_set", "target": "masters aircon", "mode": "heat", "temp_now": 23.0},
        ),
        (
            "To your normal masters I see on cool mode 23",
            {"kind": "climate_set", "target": "masters aircon", "mode": "cool", "temp_now": 23.0},
        ),
    ]

    for text, expected in cases:
        parsed = _parse_control_intent(text)
        if not parsed:
            raise RuntimeError(f"HA parser self-test failed: no parse for {text!r}")
        for key, value in expected.items():
            if parsed.get(key) != value:
                raise RuntimeError(
                    f"HA parser self-test failed for {text!r}: expected {key}={value!r}, got {parsed.get(key)!r}"
                )

    if not looks_like_ha_status_query("Can you check what's on right now in HA"):
        raise RuntimeError("HA parser self-test failed: explicit HA status query not detected")
    if not looks_like_ha_status_query("what's on right now", allow_implicit=True):
        raise RuntimeError("HA parser self-test failed: implicit HA-only status query not detected")
    if looks_like_ha_status_query("what's on right now", allow_implicit=False):
        raise RuntimeError("HA parser self-test failed: implicit status should require explicit HA context")
