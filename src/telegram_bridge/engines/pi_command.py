import shlex
from typing import Optional


def _normalized_provider(config) -> str:
    provider = str(getattr(config, "pi_provider", "ollama") or "ollama").strip()
    if provider.strip().lower() in {"ollama_ssh", "ssh"}:
        return "ollama"
    return provider


def _configured_model(config) -> str:
    return str(getattr(config, "pi_model", "qwen3-coder:30b") or "qwen3-coder:30b").strip()


def build_pi_rpc_args(
    config,
    *,
    include_no_context_files: bool,
    session_key: Optional[str],
    build_session_args_fn,
) -> list[str]:
    tools_mode = (
        str(getattr(config, "pi_tools_mode", "default") or "default")
        .strip()
        .lower()
    )
    tools_allowlist = str(getattr(config, "pi_tools_allowlist", "") or "").strip()
    extra_args = str(getattr(config, "pi_extra_args", "") or "").strip()

    args = [
        str(getattr(config, "pi_bin", "pi") or "pi").strip(),
        "--provider",
        _normalized_provider(config),
        "--model",
        _configured_model(config),
        "--mode",
        "rpc",
    ]
    args.extend(build_session_args_fn(config, session_key))
    if include_no_context_files:
        args.append("--no-context-files")
    if tools_mode in {"none", "no_tools", "disabled", "off"}:
        args.append("--no-tools")
    elif tools_mode in {"no_builtin", "no_builtin_tools"}:
        args.append("--no-builtin-tools")
    elif tools_mode in {"allowlist", "tools"} and tools_allowlist:
        args.extend(["--tools", tools_allowlist])
    elif tools_mode not in {"", "default", "all"}:
        raise RuntimeError(f"Unsupported Pi tools mode: {tools_mode}")
    if extra_args:
        args.extend(shlex.split(extra_args))
    return args


def build_pi_text_args(
    config,
    *,
    include_no_context_files: bool,
    session_key: Optional[str],
    build_pi_rpc_args_fn,
) -> list[str]:
    args = build_pi_rpc_args_fn(
        config,
        include_no_context_files=include_no_context_files,
        session_key=session_key,
    )
    normalized: list[str] = []
    skip_next = False
    for index, value in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if value == "--mode" and index + 1 < len(args):
            skip_next = True
            continue
        normalized.append(value)
    normalized.append("--print")
    return normalized
