import json
from typing import Optional


IMAGE_URL_ERROR_MARKERS = ("unknown variant image_url", "image_url", "expected text")
RPC_EMPTY_OUTPUT_MARKER = "Pi RPC did not produce any output"


def build_rpc_prompt_json(
    prompt: str,
    *,
    image_path: Optional[str] = None,
    image_paths: Optional[list[str]] = None,
    image_data_builder,
) -> str:
    normalized_image_paths: list[str] = []
    for candidate in image_paths or []:
        if candidate and candidate not in normalized_image_paths:
            normalized_image_paths.append(candidate)
    if image_path and image_path not in normalized_image_paths:
        normalized_image_paths.insert(0, image_path)

    if not normalized_image_paths:
        return json.dumps({"type": "prompt", "message": prompt})

    return json.dumps({
        "type": "prompt",
        "message": prompt.strip() or "Describe the attached image(s).",
        "images": [image_data_builder(path) for path in normalized_image_paths],
    })


def extract_rpc_response(stdout_lines: list[str]) -> str:
    agent_end_event = None
    text_parts: list[str] = []
    for line in stdout_lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "agent_end":
            agent_end_event = event
            break
        if event.get("type") == "message_update":
            delta = event.get("assistantMessageEvent", {})
            if delta.get("type") == "text_delta":
                text_parts.append(str(delta.get("delta", "")))
    if agent_end_event and isinstance(agent_end_event, dict):
        messages = agent_end_event.get("messages") or []
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                content = msg.get("content") or []
                for block in reversed(content if isinstance(content, list) else [content]):
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = str(block.get("text", "")).strip()
                        if text:
                            return text
    fallback = "".join(text_parts).strip()
    if not fallback:
        raise RuntimeError(
            "Pi RPC did not produce any output (received %d lines, agent_end=%s)"
            % (len(stdout_lines), "yes" if agent_end_event else "no")
        )
    return fallback


def should_retry_pi_text_mode(
    exc: RuntimeError,
    *,
    image_path: Optional[str] = None,
    image_paths: Optional[list[str]] = None,
) -> bool:
    if image_path or image_paths:
        return False
    return str(exc).startswith(RPC_EMPTY_OUTPUT_MARKER)
