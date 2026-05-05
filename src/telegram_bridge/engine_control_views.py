from typing import Callable, Dict, List, Optional, Tuple

from telegram_bridge.engine_catalog import PI_MODEL_PICKER_PAGE_SIZE, PI_PROVIDER_CHOICES
from telegram_bridge.state_store import State


def compact_inline_keyboard(
    buttons: List[Tuple[str, str]],
    *,
    columns: int = 2,
) -> Dict[str, object]:
    rows: List[List[Dict[str, str]]] = []
    current_row: List[Dict[str, str]] = []
    for label, callback_data in buttons:
        if len(callback_data.encode("utf-8")) > 64:
            continue
        current_row.append({"text": label, "callback_data": callback_data})
        if len(current_row) >= max(columns, 1):
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    return {"inline_keyboard": rows}


def engine_callback_data(engine_name: str, action: str) -> str:
    return f"cfg|engine|{engine_name}|{action}"


def model_callback_data(engine_name: str, action: str, value: str = "") -> str:
    if action == "reset":
        return f"cfg|model|{engine_name}|reset"
    if action == "menu":
        return f"cfg|model|{engine_name}|menu|{value}" if value else f"cfg|model|{engine_name}|menu"
    if action == "page":
        return f"cfg|model|{engine_name}|page|{value}"
    return f"cfg|model|{engine_name}|set|{value}"


def provider_callback_data(action: str, value: str = "") -> str:
    if action == "menu":
        return "cfg|provider|pi|menu"
    if action == "set":
        return f"cfg|provider|pi|set|{value}"
    return f"cfg|provider|pi|{action}"


def effort_callback_data(action: str, value: str = "") -> str:
    if action == "reset":
        return "cfg|effort|codex|reset"
    if action == "menu":
        return "cfg|effort|codex|menu"
    return f"cfg|effort|codex|set|{value}"


def pi_model_page_for_selection(model_names: List[str], current_model: str, page_size: int) -> int:
    if not model_names or page_size <= 0:
        return 0
    try:
        index = model_names.index(current_model)
    except ValueError:
        return 0
    return max(index // page_size, 0)


def clamp_page_index(page_index: Optional[int], total_items: int, page_size: int) -> int:
    if total_items <= 0 or page_size <= 0:
        return 0
    last_page = max(((total_items - 1) // page_size), 0)
    if page_index is None:
        return 0
    return min(max(page_index, 0), last_page)


def parse_page_index(raw_value: str) -> Optional[int]:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        page_index = int(value)
    except ValueError:
        return None
    return page_index if page_index >= 0 else None


def build_pi_providers_text(
    state: State,
    config,
    scope_key: str,
    *,
    build_engine_runtime_config: Callable,
    configured_pi_provider: Callable,
    build_pi_provider_source_text: Callable,
    pi_available_provider_names: Callable,
    pi_provider_description: Callable,
    pi_provider_choice_lines: Callable,
) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    provider = configured_pi_provider(display_config)
    available_providers = pi_available_provider_names(display_config)
    lines = [
        f"Pi provider: {provider}",
        f"Pi provider source: {build_pi_provider_source_text(state, scope_key)}",
        "Available Pi providers:",
    ]
    if available_providers:
        for provider_name in available_providers:
            marker = " (current)" if provider_name == provider else ""
            lines.append(f"- {provider_name}{marker} - {pi_provider_description(provider_name)}")
    else:
        lines.extend(pi_provider_choice_lines(provider))
    lines.append("Use /pi provider <name> to switch this chat.")
    return "\n".join(lines)


def build_pi_models_text(
    state: State,
    config,
    scope_key: str,
    *,
    build_engine_runtime_config: Callable,
    configured_pi_provider: Callable,
    configured_pi_model: Callable,
    build_pi_provider_source_text: Callable,
    build_pi_model_source_text: Callable,
    pi_provider_model_names: Callable,
) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    provider = configured_pi_provider(display_config)
    current_model = configured_pi_model(display_config)
    provider_source = build_pi_provider_source_text(state, scope_key)
    source_text = build_pi_model_source_text(state, scope_key)
    model_names = pi_provider_model_names(display_config)
    if not model_names:
        return "\n".join(
            [
                f"Pi provider: {provider}",
                f"Pi provider source: {provider_source}",
                "No Pi models were reported for this provider.",
                "Use /engine status to check Pi health.",
            ]
        )
    lines = [
        f"Pi provider: {provider}",
        f"Pi provider source: {provider_source}",
        f"Current Pi model: {current_model} ({source_text})",
        "Available Pi models:",
    ]
    lines.extend(f"- {model_name}" for model_name in model_names)
    return "\n".join(lines)


def build_pi_status_text(
    state: State,
    config,
    scope_key: str,
    *,
    build_engine_runtime_config: Callable,
    configured_pi_provider: Callable,
    configured_pi_model: Callable,
    build_pi_provider_source_text: Callable,
    build_pi_model_source_text: Callable,
) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    provider = configured_pi_provider(display_config)
    runner = str(getattr(display_config, "pi_runner", "ssh") or "ssh").strip().lower()
    lines = [
        f"Pi provider: {provider}",
        f"Pi provider source: {build_pi_provider_source_text(state, scope_key)}",
        f"Pi model: {configured_pi_model(display_config)}",
        f"Pi model source: {build_pi_model_source_text(state, scope_key)}",
        f"Pi runner: {getattr(display_config, 'pi_runner', 'ssh')}",
        f"Pi session mode: {getattr(display_config, 'pi_session_mode', 'none')}",
        f"Pi tools mode: {getattr(display_config, 'pi_tools_mode', 'default')}",
        "Use /engine status to check health and availability.",
    ]
    if runner in {"local", "server3"}:
        lines.insert(4, f"Pi local cwd: {getattr(display_config, 'pi_local_cwd', '')}")
    else:
        lines.insert(4, f"Pi host: {getattr(display_config, 'pi_ssh_host', 'server4-beast')}")
    lines.append("Use /pi providers or /pi provider <name> to manage Pi providers.")
    lines.append("Use /model list and /model <name> to view or change the Pi model.")
    return "\n".join(lines)


def build_engine_status_text(
    state: State,
    config,
    scope_key: str,
    *,
    state_repo,
    normalize_engine_name: Callable,
    configured_default_engine: Callable,
    selectable_engine_plugins: Callable,
    build_engine_runtime_config: Callable,
    configured_codex_reasoning_effort: Callable,
    build_pi_provider_source_text: Callable,
    build_pi_model_source_text: Callable,
    pi_provider_uses_ollama_tunnel: Callable,
    check_gemma_health: Callable,
    check_venice_health: Callable,
    check_pi_health: Callable,
    check_chatgpt_web_health: Callable,
) -> str:
    selected = state_repo.get_chat_engine(scope_key)
    effective = normalize_engine_name(selected or configured_default_engine(config))
    display_config = build_engine_runtime_config(state, config, scope_key, effective)
    lines = [
        f"Default engine: {configured_default_engine(config)}",
        f"This chat engine: {effective}",
        f"Selectable engines: {', '.join(selectable_engine_plugins(config))}",
        "Use /engine <name> or tap the buttons below to switch this chat.",
        "Use /engine reset to clear the chat override.",
    ]
    if effective == "codex":
        codex_model = str(getattr(display_config, "codex_model", "") or "").strip()
        lines.append(f"Codex model: {codex_model or '(default)'}")
        lines.append(
            f"Codex effort: {configured_codex_reasoning_effort(display_config) or '(default)'}"
        )
    if effective == "gemma":
        lines.append(f"Gemma provider: {getattr(config, 'gemma_provider', 'ollama_ssh')}")
        lines.append(f"Gemma model: {getattr(config, 'gemma_model', 'gemma4:26b')}")
        lines.append(f"Gemma host: {getattr(config, 'gemma_ssh_host', 'server4-beast')}")
        health = check_gemma_health(config)
        lines.append(f"Gemma health: {'ok' if health['ok'] else 'error'}")
        lines.append(f"Gemma response time: {health['response_ms']}ms")
        lines.append(f"Gemma model available: {'yes' if health['model_available'] else 'no'}")
        lines.append(f"Gemma last check error: {health['error'] or '(none)'}")
    if effective == "venice":
        lines.append(f"Venice base URL: {getattr(display_config, 'venice_base_url', 'https://api.venice.ai/api/v1')}")
        lines.append(f"Venice model: {getattr(display_config, 'venice_model', 'mistral-31-24b')}")
        lines.append(f"Venice temperature: {getattr(display_config, 'venice_temperature', 0.2)}")
        health = check_venice_health(config)
        lines.append(f"Venice health: {'ok' if health['ok'] else 'error'}")
        lines.append(f"Venice response time: {health['response_ms']}ms")
        lines.append(f"Venice model available: {'yes' if health['model_available'] else 'no'}")
        lines.append(f"Venice last check error: {health['error'] or '(none)'}")
    if effective == "pi":
        lines.append(f"Pi provider: {getattr(display_config, 'pi_provider', 'ollama')}")
        lines.append(f"Pi provider source: {build_pi_provider_source_text(state, scope_key)}")
        lines.append(f"Pi model: {getattr(display_config, 'pi_model', 'qwen3-coder:30b')}")
        lines.append(f"Pi model source: {build_pi_model_source_text(state, scope_key)}")
        lines.append(f"Pi runner: {getattr(display_config, 'pi_runner', 'ssh')}")
        if str(getattr(display_config, "pi_runner", "ssh") or "ssh").strip().lower() in {"local", "server3"}:
            lines.append(f"Pi local cwd: {getattr(display_config, 'pi_local_cwd', '')}")
            if pi_provider_uses_ollama_tunnel(display_config):
                if bool(getattr(display_config, "pi_ollama_tunnel_enabled", True)):
                    lines.append(
                        f"Pi Ollama tunnel: 127.0.0.1:{getattr(display_config, 'pi_ollama_tunnel_local_port', 11435)}"
                    )
                else:
                    lines.append("Pi Ollama tunnel: disabled")
            else:
                lines.append("Pi Ollama tunnel: not used for this provider")
        else:
            lines.append(f"Pi host: {getattr(display_config, 'pi_ssh_host', 'server4-beast')}")
        lines.append(f"Pi session mode: {getattr(display_config, 'pi_session_mode', 'none')}")
        lines.append(f"Pi tools mode: {getattr(display_config, 'pi_tools_mode', 'default')}")
        health = check_pi_health(display_config)
        lines.append(f"Pi health: {'ok' if health['ok'] else 'error'}")
        lines.append(f"Pi response time: {health['response_ms']}ms")
        lines.append(f"Pi version: {health['version'] or '(unknown)'}")
        lines.append(f"Pi model available: {'yes' if health['model_available'] else 'no'}")
        lines.append(f"Pi last check error: {health['error'] or '(none)'}")
        lines.append("Pi selectability: /pi providers, /pi provider <name>, /model list, /model <name>")
    if effective == "chatgptweb":
        lines.append(f"ChatGPT web URL: {getattr(display_config, 'chatgpt_web_url', 'https://chatgpt.com/')}")
        lines.append(f"ChatGPT web bridge: {getattr(display_config, 'chatgpt_web_bridge_script', '')}")
        lines.append(f"ChatGPT web Browser Brain: {getattr(display_config, 'chatgpt_web_browser_brain_url', 'http://127.0.0.1:47831')}")
        lines.append("ChatGPT web mode: experimental brittle browser bridge")
        health = check_chatgpt_web_health(display_config)
        lines.append(f"ChatGPT web health: {'ok' if health['ok'] else 'error'}")
        lines.append(f"ChatGPT web response time: {health['response_ms']}ms")
        lines.append(f"ChatGPT web Browser Brain running: {'yes' if health['running'] else 'no'}")
        lines.append(f"ChatGPT web tab visible: {'yes' if health['chatgpt_tab'] else 'no'}")
        lines.append(f"ChatGPT web last check error: {health['error'] or '(none)'}")
    return "\n".join(lines)


def build_engine_picker_markup(
    state: State,
    config,
    scope_key: str,
    *,
    model_active_engine_name: Callable,
    selectable_engine_plugins: Callable,
) -> Optional[Dict[str, object]]:
    current_engine = model_active_engine_name(state, config, scope_key)
    buttons: List[Tuple[str, str]] = []
    for engine_name in selectable_engine_plugins(config):
        label = f"{engine_name} *" if engine_name == current_engine else engine_name
        buttons.append((label, engine_callback_data(engine_name, "set")))
    if current_engine == "codex":
        buttons.append(("Model", model_callback_data(current_engine, "menu")))
    elif current_engine == "pi":
        buttons.append(("Provider", provider_callback_data("menu")))
        buttons.append(("Model", model_callback_data(current_engine, "menu")))
    buttons.append(("Reset", engine_callback_data("default", "reset")))
    markup = compact_inline_keyboard(buttons, columns=2)
    return markup if markup.get("inline_keyboard") else None


def build_provider_picker_markup(
    state: State,
    config,
    scope_key: str,
    *,
    build_engine_runtime_config: Callable,
    configured_pi_provider: Callable,
    pi_available_provider_names: Callable,
) -> Optional[Dict[str, object]]:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    current_provider = configured_pi_provider(display_config)
    provider_names = pi_available_provider_names(display_config)
    if not provider_names:
        provider_names = [provider for provider, _description in PI_PROVIDER_CHOICES]
    buttons: List[Tuple[str, str]] = []
    for provider_name in provider_names:
        label = f"{provider_name} *" if provider_name == current_provider else provider_name
        buttons.append((label, provider_callback_data("set", provider_name)))
    rows = compact_inline_keyboard(buttons, columns=2).get("inline_keyboard", [])
    rows.append(
        [
            {"text": "Back to Engine", "callback_data": engine_callback_data("pi", "menu")},
        ]
    )
    return {"inline_keyboard": rows} if rows else None


def build_effort_picker_markup(
    state: State,
    config,
    scope_key: str,
    *,
    model_active_engine_name: Callable,
    build_engine_runtime_config: Callable,
    configured_codex_model: Callable,
    configured_codex_reasoning_effort: Callable,
    supported_codex_efforts_for_model: Callable,
) -> Optional[Dict[str, object]]:
    active_engine = model_active_engine_name(state, config, scope_key)
    if active_engine != "codex":
        return None
    display_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_model = configured_codex_model(display_config)
    current_effort = configured_codex_reasoning_effort(display_config) or "(default)"
    buttons: List[Tuple[str, str]] = []
    for effort in supported_codex_efforts_for_model(current_model):
        label = f"{effort} *" if effort == current_effort else effort
        buttons.append((label, effort_callback_data("set", effort)))
    buttons.append(("Reset", effort_callback_data("reset")))
    buttons.append(("Back to Models", "cfg|model|codex|menu"))
    markup = compact_inline_keyboard(buttons, columns=2)
    return markup if markup.get("inline_keyboard") else None


def build_model_picker_markup(
    state: State,
    config,
    scope_key: str,
    *,
    page_index: Optional[int] = None,
    model_active_engine_name: Callable,
    build_engine_runtime_config: Callable,
    configured_codex_model: Callable,
    load_codex_model_choices: Callable,
    pi_provider_model_names: Callable,
    configured_pi_model: Callable,
) -> Optional[Dict[str, object]]:
    active_engine = model_active_engine_name(state, config, scope_key)
    display_config = build_engine_runtime_config(state, config, scope_key, active_engine)
    buttons: List[Tuple[str, str]] = []
    if active_engine == "codex":
        current_model = configured_codex_model(display_config) or "(default)"
        for slug, display_name in load_codex_model_choices():
            label = slug
            if slug == current_model:
                label = f"{slug} *"
            elif display_name != slug:
                label = display_name
            buttons.append((label, model_callback_data("codex", "set", slug)))
        buttons.append(("Reset", model_callback_data("codex", "reset")))
        buttons.append(("Effort", "cfg|effort|codex|menu"))
        buttons.append(("Back to Engine", engine_callback_data("codex", "menu")))
    elif active_engine == "pi":
        model_names = pi_provider_model_names(display_config)
        current_model = configured_pi_model(display_config)
        current_page = clamp_page_index(
            page_index
            if page_index is not None
            else pi_model_page_for_selection(model_names, current_model, PI_MODEL_PICKER_PAGE_SIZE),
            len(model_names),
            PI_MODEL_PICKER_PAGE_SIZE,
        )
        start = current_page * PI_MODEL_PICKER_PAGE_SIZE
        end = start + PI_MODEL_PICKER_PAGE_SIZE
        for model_name in model_names[start:end]:
            label = f"{model_name} *" if model_name == current_model else model_name
            buttons.append((label, model_callback_data("pi", "set", model_name)))
        rows = compact_inline_keyboard(buttons, columns=2).get("inline_keyboard", [])
        total_pages = max(((len(model_names) - 1) // PI_MODEL_PICKER_PAGE_SIZE) + 1, 1) if model_names else 1
        if total_pages > 1:
            nav_row: List[Dict[str, str]] = []
            if current_page > 0:
                nav_row.append({"text": "Prev", "callback_data": model_callback_data("pi", "page", str(current_page - 1))})
            nav_row.append(
                {
                    "text": f"{current_page + 1}/{total_pages}",
                    "callback_data": model_callback_data("pi", "page", str(current_page)),
                }
            )
            if current_page < total_pages - 1:
                nav_row.append({"text": "Next", "callback_data": model_callback_data("pi", "page", str(current_page + 1))})
            rows.append(nav_row)
        rows.append(
            [
                {"text": "Reset", "callback_data": model_callback_data("pi", "reset")},
                {"text": "Back to Engine", "callback_data": engine_callback_data("pi", "menu")},
            ]
        )
        return {"inline_keyboard": rows} if rows else None
    else:
        return None
    markup = compact_inline_keyboard(buttons, columns=2)
    return markup if markup.get("inline_keyboard") else None


def build_model_status_text(
    state: State,
    config,
    scope_key: str,
    *,
    model_active_engine_name: Callable,
    build_engine_runtime_config: Callable,
    configured_codex_model: Callable,
    configured_codex_reasoning_effort: Callable,
    configured_pi_provider: Callable,
    configured_pi_model: Callable,
    build_codex_model_source_text: Callable,
    build_codex_effort_source_text: Callable,
    build_pi_model_source_text: Callable,
) -> str:
    active_engine = model_active_engine_name(state, config, scope_key)
    display_config = build_engine_runtime_config(state, config, scope_key, active_engine)
    if active_engine == "codex":
        lines = [
            "Active engine: codex",
            f"Codex model: {configured_codex_model(display_config) or '(default)'}",
            f"Codex model source: {build_codex_model_source_text(state, scope_key)}",
            f"Codex effort: {configured_codex_reasoning_effort(display_config) or '(default)'}",
            f"Codex effort source: {build_codex_effort_source_text(state, scope_key)}",
            "Use /model <name> to set this chat's Codex model or tap the buttons below.",
            "Use /model reset to clear the chat override.",
        ]
        return "\n".join(lines)
    if active_engine == "pi":
        lines = [
            "Active engine: pi",
            f"Pi provider: {configured_pi_provider(display_config)}",
            f"Pi model: {configured_pi_model(display_config)}",
            f"Pi model source: {build_pi_model_source_text(state, scope_key)}",
            "Use /model list to see available Pi models for the current provider.",
            "Use /pi provider <name> to switch Pi provider for this chat.",
        ]
        return "\n".join(lines)
    return (
        f"Active engine: {active_engine}\n"
        "Model switching is currently supported for `codex` and `pi`.\n"
        "Use `/engine codex` or `/engine pi` first."
    )


def build_effort_status_text(
    state: State,
    config,
    scope_key: str,
    *,
    model_active_engine_name: Callable,
    build_engine_runtime_config: Callable,
    configured_codex_model: Callable,
    configured_codex_reasoning_effort: Callable,
    build_codex_effort_source_text: Callable,
) -> str:
    active_engine = model_active_engine_name(state, config, scope_key)
    if active_engine != "codex":
        return (
            f"Active engine: {active_engine}\n"
            "Reasoning effort switching is currently supported for `codex`.\n"
            "Use `/engine codex` first."
        )
    display_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_model = configured_codex_model(display_config) or "(default)"
    current_effort = configured_codex_reasoning_effort(display_config) or "(default)"
    return "\n".join(
        [
            "Active engine: codex",
            f"Codex model: {current_model}",
            f"Codex effort: {current_effort}",
            f"Codex effort source: {build_codex_effort_source_text(state, scope_key)}",
            "Use /effort <low|medium|high|xhigh> or tap the buttons below.",
            "Use /effort reset to clear the chat override.",
        ]
    )


def build_effort_list_text(
    state: State,
    config,
    scope_key: str,
    *,
    model_active_engine_name: Callable,
    build_engine_runtime_config: Callable,
    configured_codex_model: Callable,
    configured_codex_reasoning_effort: Callable,
    supported_codex_efforts_for_model: Callable,
) -> str:
    active_engine = model_active_engine_name(state, config, scope_key)
    if active_engine != "codex":
        return (
            f"Active engine: {active_engine}\n"
            "Reasoning effort listing is currently supported for `codex`.\n"
            "Use `/engine codex` first."
        )
    display_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_model = configured_codex_model(display_config) or "(default)"
    current_effort = configured_codex_reasoning_effort(display_config) or "(default)"
    lines = [
        "Active engine: codex",
        f"Current Codex model: {current_model}",
        f"Current Codex effort: {current_effort}",
        "Available Codex reasoning efforts for this model:",
    ]
    for effort in supported_codex_efforts_for_model(current_model):
        marker = " (current)" if effort == current_effort else ""
        lines.append(f"- {effort}{marker}")
    return "\n".join(lines)


def build_model_list_text(
    state: State,
    config,
    scope_key: str,
    *,
    model_active_engine_name: Callable,
    build_engine_runtime_config: Callable,
    configured_codex_model: Callable,
    load_codex_model_choices: Callable,
    build_pi_models_text: Callable,
) -> str:
    active_engine = model_active_engine_name(state, config, scope_key)
    display_config = build_engine_runtime_config(state, config, scope_key, active_engine)
    if active_engine == "codex":
        current_model = configured_codex_model(display_config) or "(default)"
        default_model = configured_codex_model(config) or "(default)"
        lines = [
            "Active engine: codex",
            f"Current Codex model: {current_model}",
            f"Bridge default Codex model: {default_model}",
        ]
        choices = load_codex_model_choices()
        if choices:
            lines.append("Available Codex models:")
            for slug, display_name in choices:
                marker = " (current)" if slug == current_model else ""
                if display_name != slug:
                    lines.append(f"- {slug}{marker} - {display_name}")
                else:
                    lines.append(f"- {slug}{marker}")
            lines.append("Use /model <name> with either the slug or display name.")
        else:
            lines.append("No local Codex model cache was found for a fuller list.")
            lines.append("Set any Codex model name with /model <name>.")
        return "\n".join(lines)
    if active_engine == "pi":
        return build_pi_models_text(state, config, scope_key)
    return (
        f"Active engine: {active_engine}\n"
        "Model listing is currently supported for `codex` and `pi`.\n"
        "Use `/engine codex` or `/engine pi` first."
    )
