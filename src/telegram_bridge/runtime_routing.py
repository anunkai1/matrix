"""Pure routing helpers for runtime prefix and keyword policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

try:
    from .runtime_profile import (
        BROWSER_BRAIN_KEYWORD_HELP_MESSAGE,
        HA_KEYWORD_HELP_MESSAGE,
        NEXTCLOUD_KEYWORD_HELP_MESSAGE,
        PREFIX_HELP_MESSAGE,
        SERVER3_KEYWORD_HELP_MESSAGE,
        build_browser_brain_keyword_prompt,
        build_ha_keyword_prompt,
        build_nextcloud_keyword_prompt,
        build_server3_keyword_prompt,
        command_bypasses_required_prefix,
        extract_browser_brain_keyword_request,
        extract_ha_keyword_request,
        extract_nextcloud_keyword_request,
        extract_server3_keyword_request,
        extract_youtube_link_request,
    )
except ImportError:
    from runtime_profile import (
        BROWSER_BRAIN_KEYWORD_HELP_MESSAGE,
        HA_KEYWORD_HELP_MESSAGE,
        NEXTCLOUD_KEYWORD_HELP_MESSAGE,
        PREFIX_HELP_MESSAGE,
        SERVER3_KEYWORD_HELP_MESSAGE,
        build_browser_brain_keyword_prompt,
        build_ha_keyword_prompt,
        build_nextcloud_keyword_prompt,
        build_server3_keyword_prompt,
        command_bypasses_required_prefix,
        extract_browser_brain_keyword_request,
        extract_ha_keyword_request,
        extract_nextcloud_keyword_request,
        extract_server3_keyword_request,
        extract_youtube_link_request,
    )


@dataclass(frozen=True)
class PrefixGateResult:
    prompt_input: Optional[str]
    enforce_voice_prefix_from_transcript: bool = False
    ignored: bool = False
    rejection_reason: Optional[str] = None
    rejection_message: Optional[str] = None


@dataclass(frozen=True)
class KeywordRouteResult:
    prompt_input: str
    command: Optional[str]
    stateless: bool
    priority_keyword_mode: bool
    route_kind: Optional[str] = None
    route_value: Optional[str] = None
    routed_event: Optional[str] = None
    rejection_reason: Optional[str] = None
    rejection_message: Optional[str] = None


def apply_required_prefix_gate(
    *,
    client,
    config,
    prompt_input: Optional[str],
    has_reply_context: bool,
    voice_file_id: Optional[str],
    document,
    is_private_chat: bool,
    normalize_command,
    strip_required_prefix,
) -> PrefixGateResult:
    requires_prefix_for_message = bool(config.required_prefixes) and (
        config.require_prefix_in_private or not is_private_chat
    )
    prefix_bypass_command = normalize_command(prompt_input or "")

    if (
        prompt_input is None
        or not requires_prefix_for_message
        or command_bypasses_required_prefix(client, prefix_bypass_command)
    ):
        return PrefixGateResult(prompt_input=prompt_input)

    youtube_link_mode, _ = extract_youtube_link_request(prompt_input)
    if prefix_bypass_command is None and youtube_link_mode:
        return PrefixGateResult(prompt_input=prompt_input)

    voice_without_caption = bool(voice_file_id) and not prompt_input.strip()
    if voice_without_caption:
        return PrefixGateResult(
            prompt_input=prompt_input,
            enforce_voice_prefix_from_transcript=True,
        )

    has_required_prefix, stripped_prompt = strip_required_prefix(
        prompt_input,
        config.required_prefixes,
        config.required_prefix_ignore_case,
    )
    if not has_required_prefix:
        return PrefixGateResult(prompt_input=prompt_input, ignored=True, rejection_reason="prefix_required")
    if not stripped_prompt and voice_file_id is None and document is None and not has_reply_context:
        return PrefixGateResult(
            prompt_input=stripped_prompt,
            rejection_reason="prefix_missing_action",
            rejection_message=PREFIX_HELP_MESSAGE,
        )
    return PrefixGateResult(prompt_input=stripped_prompt)


def apply_priority_keyword_routing(
    *,
    config,
    prompt_input: Optional[str],
    command: Optional[str],
    chat_id: int,
) -> KeywordRouteResult:
    if not prompt_input or not getattr(config, "keyword_routing_enabled", True):
        return KeywordRouteResult(
            prompt_input=prompt_input or "",
            command=command,
            stateless=False,
            priority_keyword_mode=False,
        )

    browser_keyword_mode, browser_request = extract_browser_brain_keyword_request(prompt_input)
    if browser_keyword_mode:
        if not browser_request.strip():
            return KeywordRouteResult(
                prompt_input=prompt_input,
                command=command,
                stateless=False,
                priority_keyword_mode=False,
                rejection_reason="browser_brain_keyword_missing_action",
                rejection_message=BROWSER_BRAIN_KEYWORD_HELP_MESSAGE,
            )
        return KeywordRouteResult(
            prompt_input=build_browser_brain_keyword_prompt(browser_request),
            command=None,
            stateless=True,
            priority_keyword_mode=True,
            routed_event="bridge.browser_brain_keyword_routed",
        )

    nextcloud_keyword_mode, nextcloud_request = extract_nextcloud_keyword_request(prompt_input)
    if nextcloud_keyword_mode:
        if not nextcloud_request.strip():
            return KeywordRouteResult(
                prompt_input=prompt_input,
                command=command,
                stateless=False,
                priority_keyword_mode=False,
                rejection_reason="nextcloud_keyword_missing_action",
                rejection_message=NEXTCLOUD_KEYWORD_HELP_MESSAGE,
            )
        return KeywordRouteResult(
            prompt_input=build_nextcloud_keyword_prompt(nextcloud_request),
            command=None,
            stateless=True,
            priority_keyword_mode=True,
            routed_event="bridge.nextcloud_keyword_routed",
        )

    server3_keyword_mode, server3_request = extract_server3_keyword_request(prompt_input)
    if server3_keyword_mode:
        if not server3_request.strip():
            return KeywordRouteResult(
                prompt_input=prompt_input,
                command=command,
                stateless=False,
                priority_keyword_mode=False,
                rejection_reason="server3_keyword_missing_action",
                rejection_message=SERVER3_KEYWORD_HELP_MESSAGE,
            )
        return KeywordRouteResult(
            prompt_input=build_server3_keyword_prompt(server3_request),
            command=None,
            stateless=True,
            priority_keyword_mode=True,
            routed_event="bridge.server3_keyword_routed",
        )

    ha_keyword_mode, ha_request = extract_ha_keyword_request(prompt_input)
    if ha_keyword_mode:
        if not ha_request.strip():
            return KeywordRouteResult(
                prompt_input=prompt_input,
                command=command,
                stateless=False,
                priority_keyword_mode=False,
                rejection_reason="ha_keyword_missing_action",
                rejection_message=HA_KEYWORD_HELP_MESSAGE,
            )
        return KeywordRouteResult(
            prompt_input=build_ha_keyword_prompt(ha_request),
            command=None,
            stateless=True,
            priority_keyword_mode=True,
            routed_event="bridge.ha_keyword_routed",
        )

    youtube_link_mode, youtube_url = extract_youtube_link_request(prompt_input)
    if command is None and youtube_link_mode:
        return KeywordRouteResult(
            prompt_input=prompt_input,
            command=None,
            stateless=True,
            priority_keyword_mode=True,
            route_kind="youtube_link",
            route_value=youtube_url,
            routed_event="bridge.youtube_link_auto_routed",
        )

    return KeywordRouteResult(
        prompt_input=prompt_input,
        command=command,
        stateless=False,
        priority_keyword_mode=False,
    )
