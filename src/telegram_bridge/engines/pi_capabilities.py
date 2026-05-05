import json
from pathlib import Path


IMAGE_CAPABLE_MODEL_SUGGESTIONS = (
    "claude-sonnet-4-5",
    "gemini-3-flash-preview",
    "grok-41-fast",
    "qwen-3-6-plus",
    "google-gemma-4-26b-a4b-it",
    "kimi-k2-6",
)


def _normalized_provider(config) -> str:
    provider = str(getattr(config, "pi_provider", "ollama") or "ollama").strip()
    if provider.strip().lower() in {"ollama_ssh", "ssh"}:
        return "ollama"
    return provider


def pi_models_path(config) -> Path:
    del config
    return Path.home() / ".pi" / "agent" / "models.json"


def model_supports_images(config) -> bool:
    model = str(getattr(config, "pi_model", "") or "").strip()
    if not model:
        return True
    models_path = pi_models_path(config)
    if not models_path.is_file():
        return True
    try:
        data = json.loads(models_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True
    providers = data.get("providers")
    if not isinstance(providers, dict):
        return True
    provider_cfg = providers.get(_normalized_provider(config))
    if not isinstance(provider_cfg, dict):
        return True
    models = provider_cfg.get("models")
    if not isinstance(models, list):
        return True
    for entry in models:
        if not isinstance(entry, dict):
            continue
        if entry.get("id") == model:
            supported_inputs = entry.get("input")
            if isinstance(supported_inputs, list) and "image" in supported_inputs:
                return True
            return False
    return True
