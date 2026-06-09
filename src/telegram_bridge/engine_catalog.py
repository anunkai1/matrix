import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


ENGINE_NAME_ALIASES = {
    "ollama": "gemma",
    "ollama(s4)": "gemma",
    "ollama-s4": "gemma",
    "ollama_s4": "gemma",
    "ollamas4": "gemma",
}
ENGINE_DISPLAY_NAMES = {
    "gemma": "ollama(s4)",
}
PI_PROVIDER_ALIASES = {
    "ollama_http": "ollama",
    "ollama_ssh": "ollama",
    "ssh": "ollama",
}
PI_PROVIDER_CHOICES = (
    ("ollama", "local Ollama or SSH-tunneled Ollama"),
    ("venice", "Venice API models"),
    ("deepseek", "DeepSeek API models"),
    ("minimax", "MiniMax API models (Anthropic-compatible)"),
)
PI_MODEL_PICKER_PAGE_SIZE = 16
# Pi's `--thinking` flag accepts these levels. We mirror them for the bridge
# effort picker when the active engine is `pi` and the model supports reasoning.
PI_THINKING_LEVEL_CHOICES = (
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)
DEFAULT_PI_THINKING_LEVELS = ("low", "medium", "high", "xhigh")


def _engines_config(config):
    return getattr(config, "engines", config)


def normalize_engine_name(engine_name: str) -> str:
    normalized = str(engine_name or "").strip().lower()
    return ENGINE_NAME_ALIASES.get(normalized, normalized)


def display_engine_name(engine_name: str) -> str:
    normalized = normalize_engine_name(engine_name)
    if not normalized:
        return ""
    return ENGINE_DISPLAY_NAMES.get(normalized, normalized)


def configured_default_engine(config) -> str:
    engines = _engines_config(config)
    return normalize_engine_name(getattr(engines, "engine_plugin", "codex") or "codex")


def selectable_engine_plugins(config) -> List[str]:
    engines = _engines_config(config)
    configured: List[str] = []
    for value in getattr(engines, "selectable_engine_plugins", ["codex", "gemma", "pi"]):
        normalized = normalize_engine_name(str(value))
        if normalized and normalized not in configured:
            configured.append(normalized)
    default_engine = configured_default_engine(config)
    if default_engine not in configured:
        configured.insert(0, default_engine)
    return configured


def selectable_engine_display_names(config) -> List[str]:
    return [display_engine_name(engine_name) for engine_name in selectable_engine_plugins(config)]


def configured_pi_provider(config) -> str:
    engines = _engines_config(config)
    provider = str(getattr(engines, "pi_provider", "ollama") or "ollama").strip().lower()
    return PI_PROVIDER_ALIASES.get(provider, provider) or "ollama"


def normalize_pi_provider_name(provider_name: str) -> str:
    provider = str(provider_name or "").strip().lower()
    return PI_PROVIDER_ALIASES.get(provider, provider)


def configured_pi_model(config) -> str:
    engines = _engines_config(config)
    return str(getattr(engines, "pi_model", "qwen3-coder:30b") or "qwen3-coder:30b").strip() or "qwen3-coder:30b"


def configured_pi_thinking_level(config) -> str:
    engines = _engines_config(config)
    return str(getattr(engines, "pi_thinking_level", "") or "").strip().lower()


def _pi_thinking_level_is_valid(level_name: str) -> bool:
    return level_name in PI_THINKING_LEVEL_CHOICES


def supported_pi_thinking_levels_for_model(provider: str, model_name: str) -> List[str]:
    """Return the thinking levels the current Pi model+provider actually exposes.

    Falls back to the default six-level set when the model advertises
    `reasoning: true` and no explicit `thinkingLevelMap`. Returns an empty list
    when the model clearly does not support reasoning.
    """

    normalized_provider = normalize_pi_provider_name(provider)
    normalized_model = str(model_name or "").strip()
    if not normalized_model:
        return list(DEFAULT_PI_THINKING_LEVELS)

    models_path = Path.home() / ".pi" / "agent" / "models.json"
    if not models_path.is_file():
        return list(DEFAULT_PI_THINKING_LEVELS)
    try:
        data = json.loads(models_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return list(DEFAULT_PI_THINKING_LEVELS)
    providers = data.get("providers") if isinstance(data, dict) else None
    if not isinstance(providers, dict):
        return list(DEFAULT_PI_THINKING_LEVELS)
    provider_cfg = providers.get(normalized_provider)
    if not isinstance(provider_cfg, dict):
        return list(DEFAULT_PI_THINKING_LEVELS)
    models = provider_cfg.get("models")
    if not isinstance(models, list):
        return list(DEFAULT_PI_THINKING_LEVELS)
    for entry in models:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("id", "") or "").strip() != normalized_model:
            continue
        if not bool(entry.get("reasoning", False)):
            return []
        raw_map = entry.get("thinkingLevelMap")
        if not isinstance(raw_map, dict) or not raw_map:
            return list(PI_THINKING_LEVEL_CHOICES)
        resolved: List[str] = []
        for level in PI_THINKING_LEVEL_CHOICES:
            if level not in raw_map:
                resolved.append(level)
                continue
            value = raw_map[level]
            if value is None:
                continue
            resolved.append(level)
        return resolved or list(DEFAULT_PI_THINKING_LEVELS)
    return list(DEFAULT_PI_THINKING_LEVELS)


def resolve_pi_thinking_level_candidate(
    available_levels: List[str],
    requested_level: str,
) -> Optional[str]:
    normalized = str(requested_level or "").strip().lower()
    if not normalized or not _pi_thinking_level_is_valid(normalized):
        return None
    for level in available_levels or ():
        if level == normalized:
            return level
    return None


def configured_gemma_model(config) -> str:
    engines = _engines_config(config)
    return str(getattr(engines, "gemma_model", "gemma4:26b") or "gemma4:26b").strip() or "gemma4:26b"


def pi_provider_uses_ollama_tunnel(config) -> bool:
    return configured_pi_provider(config) == "ollama"


def configured_codex_model(config) -> str:
    engines = _engines_config(config)
    return str(getattr(engines, "codex_model", "") or "").strip()


def configured_codex_reasoning_effort(config) -> str:
    engines = _engines_config(config)
    return str(getattr(engines, "codex_reasoning_effort", "") or "").strip().lower()


def codex_models_cache_path() -> Path:
    codex_home = str(os.getenv("CODEX_HOME", "") or "").strip()
    if codex_home:
        return Path(codex_home).expanduser() / "models_cache.json"
    return Path.home() / ".codex" / "models_cache.json"


def load_codex_model_catalog() -> List[Dict[str, object]]:
    cache_path = codex_models_cache_path()
    if not cache_path.exists():
        return []
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    models = data.get("models")
    if not isinstance(models, list):
        return []
    catalog: List[Dict[str, object]] = []
    seen: Set[str] = set()
    for item in models:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug", "") or "").strip()
        if not slug:
            continue
        visibility = str(item.get("visibility", "") or "").strip().lower()
        if visibility and visibility != "list":
            continue
        key = slug.casefold()
        if key in seen:
            continue
        seen.add(key)
        display_name = str(item.get("display_name", "") or "").strip() or slug
        efforts: List[str] = []
        raw_efforts = item.get("supported_reasoning_levels")
        if isinstance(raw_efforts, list):
            for raw_effort in raw_efforts:
                if not isinstance(raw_effort, dict):
                    continue
                effort = str(raw_effort.get("effort", "") or "").strip().lower()
                if effort and effort not in efforts:
                    efforts.append(effort)
        catalog.append(
            {
                "slug": slug,
                "display_name": display_name,
                "supported_efforts": efforts,
            }
        )
    return catalog


def load_codex_model_choices() -> List[Tuple[str, str]]:
    choices: List[Tuple[str, str]] = []
    for item in load_codex_model_catalog():
        slug = str(item.get("slug", "") or "").strip()
        if not slug:
            continue
        display_name = str(item.get("display_name", "") or "").strip() or slug
        choices.append((slug, display_name))
    return choices


def supported_codex_efforts_for_model(model_name: str) -> List[str]:
    normalized_model = str(model_name or "").strip()
    default_efforts = ["low", "medium", "high", "xhigh"]
    if not normalized_model:
        return default_efforts
    folded = normalized_model.casefold()
    for item in load_codex_model_catalog():
        slug = str(item.get("slug", "") or "").strip()
        display_name = str(item.get("display_name", "") or "").strip()
        if slug.casefold() != folded and display_name.casefold() != folded:
            continue
        efforts = [
            str(value).strip().lower()
            for value in item.get("supported_efforts", [])
            if str(value).strip()
        ]
        return efforts or default_efforts
    return default_efforts


def resolve_codex_effort_candidate(model_name: str, requested_effort: str) -> Optional[str]:
    normalized_effort = str(requested_effort or "").strip().lower()
    if not normalized_effort:
        return None
    for effort in supported_codex_efforts_for_model(model_name):
        if effort == normalized_effort:
            return effort
    return None


def resolve_codex_model_candidate(requested_model: str) -> str:
    requested = str(requested_model or "").strip()
    if not requested:
        return ""
    folded = requested.casefold()
    for slug, display_name in load_codex_model_choices():
        if slug.casefold() == folded or display_name.casefold() == folded:
            return slug
    return requested
