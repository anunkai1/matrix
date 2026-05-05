import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


ENGINE_NAME_ALIASES = {
    "chatgpt": "chatgptweb",
    "chatgpt_web": "chatgptweb",
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
)
PI_MODEL_PICKER_PAGE_SIZE = 16


def normalize_engine_name(engine_name: str) -> str:
    normalized = str(engine_name or "").strip().lower()
    return ENGINE_NAME_ALIASES.get(normalized, normalized)


def configured_default_engine(config) -> str:
    return normalize_engine_name(getattr(config, "engine_plugin", "codex") or "codex")


def selectable_engine_plugins(config) -> List[str]:
    configured: List[str] = []
    for value in getattr(config, "selectable_engine_plugins", ["codex", "gemma", "pi"]):
        normalized = normalize_engine_name(str(value))
        if normalized and normalized not in configured:
            configured.append(normalized)
    default_engine = configured_default_engine(config)
    if default_engine not in configured:
        configured.insert(0, default_engine)
    return configured


def configured_pi_provider(config) -> str:
    provider = str(getattr(config, "pi_provider", "ollama") or "ollama").strip().lower()
    return PI_PROVIDER_ALIASES.get(provider, provider) or "ollama"


def normalize_pi_provider_name(provider_name: str) -> str:
    provider = str(provider_name or "").strip().lower()
    return PI_PROVIDER_ALIASES.get(provider, provider)


def configured_pi_model(config) -> str:
    return str(getattr(config, "pi_model", "qwen3-coder:30b") or "qwen3-coder:30b").strip() or "qwen3-coder:30b"


def pi_provider_uses_ollama_tunnel(config) -> bool:
    return configured_pi_provider(config) == "ollama"


def configured_codex_model(config) -> str:
    return str(getattr(config, "codex_model", "") or "").strip()


def configured_codex_reasoning_effort(config) -> str:
    return str(getattr(config, "codex_reasoning_effort", "") or "").strip().lower()


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
