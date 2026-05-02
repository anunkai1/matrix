import logging
from typing import List, Optional

try:
    from . import attachment_processing
    from .channel_adapter import ChannelAdapter
    from .handler_models import DocumentPayload
    from .state_store import State
except ImportError:
    import attachment_processing
    from channel_adapter import ChannelAdapter
    from handler_models import DocumentPayload
    from state_store import State


build_active_voice_alias_replacements = attachment_processing.build_active_voice_alias_replacements
build_voice_alias_suggestions_message = attachment_processing.build_voice_alias_suggestions_message


def build_voice_alias_help_text() -> str:
    return (
        "Voice alias learning commands:\n"
        "/voice-alias list - show pending learned corrections\n"
        "/voice-alias approve <id> - approve one suggestion\n"
        "/voice-alias reject <id> - reject one suggestion\n"
        "/voice-alias add <source> => <target> - add approved alias manually"
    )


def parse_voice_alias_suggestion_id(tail: str, action: str) -> Optional[int]:
    prefix = f"{action} "
    if not tail.lower().startswith(prefix):
        return None
    value = tail[len(prefix):].strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def handle_voice_alias_command(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    del config
    learning_store = getattr(state, "voice_alias_learning_store", None)
    if learning_store is None:
        client.send_message(
            chat_id,
            "Voice alias learning is disabled.",
            reply_to_message_id=message_id,
        )
        return True

    pieces = raw_text.strip().split(maxsplit=1)
    tail = pieces[1].strip() if len(pieces) > 1 else ""
    if not tail or tail.lower() == "help":
        client.send_message(
            chat_id,
            build_voice_alias_help_text(),
            reply_to_message_id=message_id,
        )
        return True

    if tail.lower() == "list":
        pending = learning_store.list_pending()
        if not pending:
            client.send_message(
                chat_id,
                "No pending learned voice alias suggestions.",
                reply_to_message_id=message_id,
            )
            return True
        lines = ["Pending voice alias suggestions:"]
        for suggestion in pending:
            lines.append(
                f"- #{suggestion.suggestion_id}: `{suggestion.source}` => `{suggestion.target}` (seen {suggestion.count}x)"
            )
        lines.append("Approve with: `/voice-alias approve <id>`")
        lines.append("Reject with: `/voice-alias reject <id>`")
        client.send_message(chat_id, "\n".join(lines), reply_to_message_id=message_id)
        return True

    approve_id = parse_voice_alias_suggestion_id(tail, "approve")
    if approve_id is not None:
        approved = learning_store.approve(approve_id)
        if approved is None:
            client.send_message(
                chat_id,
                f"No pending suggestion with id {approve_id}.",
                reply_to_message_id=message_id,
            )
            return True
        client.send_message(
            chat_id,
            f"Approved voice alias #{approve_id}: `{approved.source}` => `{approved.target}`",
            reply_to_message_id=message_id,
        )
        return True

    reject_id = parse_voice_alias_suggestion_id(tail, "reject")
    if reject_id is not None:
        rejected = learning_store.reject(reject_id)
        if rejected is None:
            client.send_message(
                chat_id,
                f"No pending suggestion with id {reject_id}.",
                reply_to_message_id=message_id,
            )
            return True
        client.send_message(
            chat_id,
            f"Rejected voice alias #{reject_id}: `{rejected.source}` => `{rejected.target}`",
            reply_to_message_id=message_id,
        )
        return True

    if tail.lower().startswith("add "):
        payload = tail[4:].strip()
        if "=>" not in payload:
            client.send_message(
                chat_id,
                "Usage: /voice-alias add <source> => <target>",
                reply_to_message_id=message_id,
            )
            return True
        source, target = payload.split("=>", 1)
        source = source.strip()
        target = target.strip()
        if not source or not target:
            client.send_message(
                chat_id,
                "Usage: /voice-alias add <source> => <target>",
                reply_to_message_id=message_id,
            )
            return True
        try:
            added_source, added_target = learning_store.add_manual(source, target)
        except ValueError:
            client.send_message(
                chat_id,
                "Usage: /voice-alias add <source> => <target>",
                reply_to_message_id=message_id,
            )
            return True
        client.send_message(
            chat_id,
            f"Added manual voice alias: `{added_source}` => `{added_target}`",
            reply_to_message_id=message_id,
        )
        return True

    client.send_message(
        chat_id,
        build_voice_alias_help_text(),
        reply_to_message_id=message_id,
    )
    return True


def maybe_process_voice_alias_learning_confirmation(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    prompt_input: str,
    command: Optional[str],
    priority_keyword_mode: bool,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    photo_file_ids: Optional[List[str]] = None,
) -> None:
    if not prompt_input.strip():
        return
    if command is not None:
        return
    if priority_keyword_mode:
        return
    if photo_file_id or photo_file_ids or voice_file_id or document is not None:
        return

    learning_store = getattr(state, "voice_alias_learning_store", None)
    if learning_store is None:
        return

    try:
        result = learning_store.consume_confirmation(
            chat_id=chat_id,
            confirmed_text=prompt_input,
            active_replacements=build_active_voice_alias_replacements(config, state),
        )
    except Exception:
        logging.exception("Failed to process voice alias learning confirmation")
        return

    if not result.suggestion_created:
        return

    message = build_voice_alias_suggestions_message(result.suggestion_created)
    if not message:
        return
    client.send_message(
        chat_id,
        message,
        reply_to_message_id=message_id,
    )
