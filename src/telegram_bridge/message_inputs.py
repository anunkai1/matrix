import re
import time
from typing import Dict, List, Optional

from telegram_bridge.conversation_scope import build_telegram_scope_key, parse_telegram_scope_key
from telegram_bridge.handler_models import DocumentPayload
from telegram_bridge.state_store import RecentPhotoSelection, State

def pick_largest_photo_file_id(photo_items: List[object]) -> Optional[str]:
    best_file_id: Optional[str] = None
    best_size = -1
    for item in photo_items:
        if not isinstance(item, dict):
            continue
        file_id = item.get("file_id")
        if not isinstance(file_id, str) or not file_id.strip():
            continue
        file_size = item.get("file_size")
        size_score = file_size if isinstance(file_size, int) else 0
        if size_score >= best_size:
            best_size = size_score
            best_file_id = file_id.strip()
    return best_file_id

def extract_discrete_photo_file_ids(photo_items: List[object]) -> List[str]:
    has_transport_descriptors = any(
        isinstance(item, dict)
        and isinstance(item.get("mime_type"), str)
        and item.get("mime_type", "").strip()
        for item in photo_items
    )
    if not has_transport_descriptors:
        return []

    photo_file_ids: List[str] = []
    for item in photo_items:
        if not isinstance(item, dict):
            continue
        file_id = item.get("file_id")
        if not isinstance(file_id, str):
            continue
        normalized = file_id.strip()
        if not normalized or normalized in photo_file_ids:
            continue
        photo_file_ids.append(normalized)
    return photo_file_ids

def normalize_optional_text(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return value.strip()

def iter_media_group_messages(message: Dict[str, object]) -> List[Dict[str, object]]:
    grouped = message.get("media_group_messages")
    if isinstance(grouped, list):
        messages = [item for item in grouped if isinstance(item, dict)]
        if messages:
            return messages
    return [message]

def collapse_media_group_updates(updates: List[Dict[str, object]]) -> List[Dict[str, object]]:
    collapsed: List[Dict[str, object]] = []
    index = 0
    while index < len(updates):
        update = updates[index]
        message = update.get("message")
        if not isinstance(message, dict):
            collapsed.append(update)
            index += 1
            continue

        media_group_id = message.get("media_group_id")
        chat = message.get("chat")
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        if not isinstance(media_group_id, str) or not media_group_id.strip() or not isinstance(chat_id, int):
            collapsed.append(update)
            index += 1
            continue

        grouped_updates = [update]
        next_index = index + 1
        while next_index < len(updates):
            candidate_update = updates[next_index]
            candidate_message = candidate_update.get("message")
            if not isinstance(candidate_message, dict):
                break
            candidate_group_id = candidate_message.get("media_group_id")
            candidate_chat = candidate_message.get("chat")
            candidate_chat_id = candidate_chat.get("id") if isinstance(candidate_chat, dict) else None
            if candidate_group_id != media_group_id or candidate_chat_id != chat_id:
                break
            grouped_updates.append(candidate_update)
            next_index += 1

        if len(grouped_updates) == 1:
            collapsed.append(update)
            index = next_index
            continue

        grouped_messages = [
            candidate_update["message"]
            for candidate_update in grouped_updates
            if isinstance(candidate_update.get("message"), dict)
        ]
        combined_update = dict(update)
        combined_message = dict(message)
        combined_message["media_group_messages"] = grouped_messages
        for field_name in ("caption", "text"):
            if normalize_optional_text(combined_message.get(field_name)):
                continue
            for grouped_message in grouped_messages:
                candidate_text = normalize_optional_text(grouped_message.get(field_name))
                if candidate_text:
                    combined_message[field_name] = candidate_text
                    break
        combined_update["message"] = combined_message
        collapsed.append(combined_update)
        index = next_index

    return collapsed

def build_reply_context_prompt(message: Dict[str, object]) -> str:
    reply_to = message.get("reply_to_message")
    if not isinstance(reply_to, dict):
        return ""

    reply_text = normalize_optional_text(reply_to.get("text"))
    reply_caption = normalize_optional_text(reply_to.get("caption"))
    quoted_text = reply_text or reply_caption or ""
    media_context = describe_message_media(reply_to)
    if not quoted_text and not media_context:
        return ""

    sender_name = extract_sender_name(reply_to)
    sender_line = ""
    if sender_name != "Telegram User":
        sender_line = f"Original Message Author: {sender_name}\n"

    body_parts: List[str] = []
    reply_message_id = reply_to.get("message_id")
    if isinstance(reply_message_id, int):
        body_parts.append(f"Original Telegram Message ID: {reply_message_id}")
    if quoted_text:
        body_parts.append("Message User Replied To:\n" f"{quoted_text}")
    if media_context:
        body_parts.append(media_context)

    return "Reply Context:\n" + sender_line + "\n\n".join(body_parts)

TELEGRAM_CONTEXT_TARGET_HINT_RE = re.compile(
    r"(?i)\b("
    r"message[_ ]id|reply[_ ]to[_ ]message[_ ]id|"
    r"use this message id|this message|reply here|reply to this|"
    r"to this chat message|reply to this chat"
    r")\b"
)

def should_include_telegram_context_prompt(
    prompt_input: Optional[str],
    reply_context_prompt: str,
    channel_name: str = "telegram",
) -> bool:
    if reply_context_prompt.strip():
        return True
    prompt_text = (prompt_input or "").strip()
    if not prompt_text:
        return False
    if (channel_name or "telegram").strip().lower() == "telegram":
        return True
    return TELEGRAM_CONTEXT_TARGET_HINT_RE.search(prompt_text) is not None

def build_telegram_context_prompt(
    chat_id: int,
    message_thread_id: Optional[int],
    scope_key: str,
    message_id: Optional[int],
    message: Dict[str, object],
) -> str:
    lines = ["Current Telegram Context:"]
    lines.append(f"- Chat ID: {chat_id}")
    if message_thread_id is not None:
        lines.append(f"- Topic ID: {message_thread_id}")
    if isinstance(message_id, int):
        lines.append(f"- Current Message ID: {message_id}")
    lines.append(f"- Scope Key: {scope_key}")

    reply_to = message.get("reply_to_message")
    if isinstance(reply_to, dict):
        reply_message_id = reply_to.get("message_id")
        if isinstance(reply_message_id, int):
            lines.append(f"- Replied-To Message ID: {reply_message_id}")

    lines.append(
        '- If the user asks to reply "here" or "to this message", '
        "default to Current Message ID unless they specify another numeric target."
    )
    lines.append(
        "- For Telegram replies, files, photos, documents, or attachments, treat this "
        "current chat/topic as authoritative. Do not infer a different chat from logs, "
        "session databases, allowlists, or recent activity."
    )
    lines.append(
        "- If the current Telegram target is missing or ambiguous, ask the user for the "
        "destination before sending. Never fall back to a different chat ID."
    )
    return "\n".join(lines)

def select_media_prompt(text: Optional[str], caption: Optional[str], default_prompt: str) -> str:
    text_value = text or ""
    caption_value = caption or ""
    if caption_value and text_value and caption_value != text_value:
        return f"{caption_value}\n\n{text_value}"
    if caption_value:
        return caption_value
    if text_value:
        return text_value
    return default_prompt

def extract_document_payload(message: Dict[str, object]) -> Optional[DocumentPayload]:
    document = message.get("document")
    if not isinstance(document, dict):
        return None

    file_id = document.get("file_id")
    if not isinstance(file_id, str) or not file_id.strip():
        return None

    file_name = document.get("file_name")
    mime_type = document.get("mime_type")
    return DocumentPayload(
        file_id=file_id.strip(),
        file_name=file_name.strip() if isinstance(file_name, str) and file_name.strip() else "unnamed",
        mime_type=mime_type.strip() if isinstance(mime_type, str) and mime_type.strip() else "unknown",
    )

def extract_message_media_payload(
    message: Dict[str, object],
) -> tuple[Optional[str], Optional[str], Optional[DocumentPayload]]:
    photo_file_ids = extract_message_photo_file_ids(message)
    if photo_file_ids:
        return photo_file_ids[0], None, None

    for candidate in iter_media_group_messages(message):
        voice = candidate.get("voice")
        if isinstance(voice, dict):
            voice_file_id = voice.get("file_id")
            if isinstance(voice_file_id, str) and voice_file_id.strip():
                return None, voice_file_id.strip(), None

        document = extract_document_payload(candidate)
        if document is not None:
            return None, None, document

    return None, None, None

def extract_message_photo_file_ids(message: Dict[str, object]) -> List[str]:
    photo_file_ids: List[str] = []
    for candidate in iter_media_group_messages(message):
        photo_items = candidate.get("photo")
        if not isinstance(photo_items, list) or not photo_items:
            continue
        discrete_photo_file_ids = extract_discrete_photo_file_ids(photo_items)
        if discrete_photo_file_ids:
            for file_id in discrete_photo_file_ids:
                if file_id not in photo_file_ids:
                    photo_file_ids.append(file_id)
            continue
        file_id = pick_largest_photo_file_id(photo_items)
        if not file_id or file_id in photo_file_ids:
            continue
        photo_file_ids.append(file_id)
    return photo_file_ids

RECENT_SCOPE_PHOTO_TTL_SECONDS = 600

def remember_recent_scope_photos(
    state: State,
    scope_key: str,
    message_id: int,
    photo_file_ids: List[str],
) -> None:
    if not photo_file_ids:
        return
    now = time.time()
    scope_candidates = {scope_key}
    try:
        conversation_scope = parse_telegram_scope_key(scope_key)
    except ValueError:
        conversation_scope = None
    if conversation_scope is not None:
        scope_candidates.add(build_telegram_scope_key(conversation_scope.chat_id))
    selection = RecentPhotoSelection(
        photo_file_ids=list(photo_file_ids),
        message_id=message_id,
        captured_at=now,
    )
    with state.lock:
        for candidate in scope_candidates:
            state.recent_scope_photos[candidate] = selection
        expired_scope_keys = [
            candidate
            for candidate, candidate_selection in state.recent_scope_photos.items()
            if now - candidate_selection.captured_at > RECENT_SCOPE_PHOTO_TTL_SECONDS
        ]
        for candidate in expired_scope_keys:
            state.recent_scope_photos.pop(candidate, None)

def get_recent_scope_photos(state: State, scope_key: str) -> List[str]:
    now = time.time()
    scope_candidates = [scope_key]
    try:
        conversation_scope = parse_telegram_scope_key(scope_key)
    except ValueError:
        conversation_scope = None
    if conversation_scope is not None:
        base_scope_key = build_telegram_scope_key(conversation_scope.chat_id)
        if base_scope_key not in scope_candidates:
            scope_candidates.append(base_scope_key)
    with state.lock:
        for candidate in scope_candidates:
            selection = state.recent_scope_photos.get(candidate)
            if selection is None:
                continue
            if now - selection.captured_at > RECENT_SCOPE_PHOTO_TTL_SECONDS:
                state.recent_scope_photos.pop(candidate, None)
                continue
            return list(selection.photo_file_ids)
    return []

def describe_message_media(message: Dict[str, object]) -> str:
    photo_file_ids = extract_message_photo_file_ids(message)
    _, voice_file_id, document = extract_message_media_payload(message)
    if photo_file_ids:
        if len(photo_file_ids) > 1:
            return "В исходном сообщении были изображения."
        return "В исходном сообщении было изображение."
    if voice_file_id:
        return "В исходном сообщении было голосовое сообщение."
    if document is not None:
        if document.file_name and document.file_name != "unnamed":
            return f"В исходном сообщении был файл: {document.file_name}."
        return "В исходном сообщении был файл."
    return ""

def extract_prompt_and_media(
    message: Dict[str, object],
) -> tuple[Optional[str], List[str], Optional[str], Optional[DocumentPayload]]:
    text = normalize_optional_text(message.get("text"))
    caption = normalize_optional_text(message.get("caption"))

    photo_file_ids = extract_message_photo_file_ids(message)
    _, voice_file_id, document = extract_message_media_payload(message)
    if photo_file_ids:
        default_prompt = "Please analyze these images." if len(photo_file_ids) > 1 else "Please analyze this image."
        prompt = select_media_prompt(text, caption, default_prompt)
        return prompt, photo_file_ids, None, None
    if voice_file_id:
        prompt = select_media_prompt(text, caption, "")
        return prompt, [], voice_file_id, None
    if document is not None:
        prompt = select_media_prompt(text, caption, "Please analyze this file.")
        return prompt, [], None, document

    reply_to = message.get("reply_to_message")
    if isinstance(reply_to, dict):
        reply_photo_file_ids = extract_message_photo_file_ids(reply_to)
        _, reply_voice_file_id, reply_document = extract_message_media_payload(reply_to)
        if reply_photo_file_ids:
            default_prompt = (
                "Please analyze the referenced images."
                if len(reply_photo_file_ids) > 1
                else "Please analyze the referenced image."
            )
            prompt = select_media_prompt(text, caption, default_prompt)
            return prompt, reply_photo_file_ids, None, None
        if reply_voice_file_id:
            prompt = select_media_prompt(
                text,
                caption,
                "Please transcribe the referenced voice message.",
            )
            return prompt, [], reply_voice_file_id, None
        if reply_document is not None:
            prompt = select_media_prompt(text, caption, "Please analyze the referenced file.")
            return prompt, [], None, reply_document

    if text is not None:
        return text, [], None, None

    return None, [], None, None

def extract_sender_name(message: Dict[str, object]) -> str:
    sender = message.get("from")
    if isinstance(sender, dict):
        first = sender.get("first_name")
        last = sender.get("last_name")
        username = sender.get("username")
        parts: List[str] = []
        if isinstance(first, str) and first.strip():
            parts.append(first.strip())
        if isinstance(last, str) and last.strip():
            parts.append(last.strip())
        if parts:
            return " ".join(parts)
        if isinstance(username, str) and username.strip():
            return username.strip()
    return "Telegram User"
