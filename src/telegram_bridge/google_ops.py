import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 fallback not expected here
    ZoneInfo = None  # type: ignore


TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GMAIL_MESSAGES_LIST_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_MESSAGE_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
GMAIL_SEND_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
CALENDAR_EVENTS_ENDPOINT = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"


class GoogleOpsError(RuntimeError):
    """Raised when Google OAuth or API operations fail."""


@dataclass
class GmailMessageSummary:
    message_id: str
    from_value: str
    subject: str
    date: str
    snippet: str


@dataclass
class CalendarEventSummary:
    event_id: str
    summary: str
    start: str
    end: str
    html_link: str


class GoogleOpsClient:
    def __init__(
        self,
        client_secret_path: str,
        token_path: str,
        default_timezone: str = "Australia/Brisbane",
    ) -> None:
        self.client_secret_path = Path(client_secret_path).expanduser()
        self.token_path = Path(token_path).expanduser()
        self.default_timezone = default_timezone

    def _parse_json_bytes(self, payload: bytes) -> Dict[str, Any]:
        text = payload.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GoogleOpsError(f"Expected JSON response, got: {text[:300]}") from exc
        if not isinstance(parsed, dict):
            raise GoogleOpsError("Expected JSON object response")
        return parsed

    def _post_form(
        self,
        url: str,
        fields: Dict[str, str],
        timeout_seconds: int = 30,
    ) -> Tuple[int, Dict[str, Any]]:
        body = urllib.parse.urlencode(fields).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read()
                status = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            status = exc.code
        return status, self._parse_json_bytes(payload)

    def _request_json(
        self,
        method: str,
        url: str,
        access_token: str,
        body: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 30,
    ) -> Tuple[int, Dict[str, Any]]:
        encoded_body: Optional[bytes] = None
        headers = {"Authorization": f"Bearer {access_token}"}
        if body is not None:
            encoded_body = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url,
            data=encoded_body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read()
                status = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            status = exc.code
        return status, self._parse_json_bytes(payload)

    def _load_client_credentials(self) -> Dict[str, str]:
        if not self.client_secret_path.exists():
            raise GoogleOpsError(f"Client secret JSON not found: {self.client_secret_path}")
        data = json.loads(self.client_secret_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise GoogleOpsError("Client secret JSON is invalid")
        root = data.get("installed") or data.get("web") or data
        if not isinstance(root, dict):
            raise GoogleOpsError("Client secret JSON missing 'installed'/'web' object")
        client_id = str(root.get("client_id", "")).strip()
        client_secret = str(root.get("client_secret", "")).strip()
        if not client_id or not client_secret:
            raise GoogleOpsError("Client secret JSON missing client_id/client_secret")
        return {"client_id": client_id, "client_secret": client_secret}

    def _load_token_doc(self) -> Dict[str, Any]:
        if not self.token_path.exists():
            raise GoogleOpsError(
                f"OAuth token JSON not found: {self.token_path}. Complete OAuth grant first."
            )
        data = json.loads(self.token_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise GoogleOpsError("OAuth token JSON is invalid")
        return data

    def _atomic_write_token_doc(self, token_doc: Dict[str, Any]) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.token_path.parent, 0o700)
        tmp_path = self.token_path.with_suffix(self.token_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(token_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(self.token_path)
        os.chmod(self.token_path, 0o600)

    def _refresh_access_token(self) -> str:
        creds = self._load_client_credentials()
        token_doc = self._load_token_doc()
        refresh_token = str(token_doc.get("refresh_token", "")).strip()
        if not refresh_token:
            raise GoogleOpsError("OAuth token JSON missing refresh_token")

        status, payload = self._post_form(
            TOKEN_ENDPOINT,
            {
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if status >= 400 or "access_token" not in payload:
            raise GoogleOpsError(f"Access-token refresh failed ({status}): {payload}")

        token_doc.update(payload)
        token_doc["refresh_token"] = refresh_token
        token_doc["refreshed_at_utc"] = datetime.now(timezone.utc).isoformat()
        token_doc["token_endpoint"] = TOKEN_ENDPOINT
        self._atomic_write_token_doc(token_doc)
        return str(payload["access_token"])

    @staticmethod
    def _header_value(headers: Any, key_name: str) -> str:
        if not isinstance(headers, list):
            return ""
        key_lower = key_name.lower()
        for item in headers:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            if isinstance(name, str) and name.lower() == key_lower and isinstance(value, str):
                return value.strip()
        return ""

    def gmail_list_unread(self, limit: int) -> List[GmailMessageSummary]:
        clamped_limit = max(1, min(limit, 50))
        access_token = self._refresh_access_token()
        list_url = (
            f"{GMAIL_MESSAGES_LIST_ENDPOINT}?"
            f"maxResults={clamped_limit}&q={urllib.parse.quote('is:unread')}"
        )
        status, payload = self._request_json("GET", list_url, access_token)
        if status >= 400:
            raise GoogleOpsError(f"Gmail unread list failed ({status}): {payload}")

        messages = payload.get("messages")
        if not isinstance(messages, list):
            return []

        out: List[GmailMessageSummary] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            message_id = str(item.get("id", "")).strip()
            if not message_id:
                continue
            out.append(self.gmail_read_message(message_id))
            if len(out) >= clamped_limit:
                break
        return out

    def gmail_read_message(self, message_id: str) -> GmailMessageSummary:
        normalized_id = message_id.strip()
        if not normalized_id:
            raise GoogleOpsError("Message id is required")
        access_token = self._refresh_access_token()
        encoded_id = urllib.parse.quote(normalized_id, safe="")
        detail_url = (
            GMAIL_MESSAGE_ENDPOINT.format(message_id=encoded_id)
            + "?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date"
        )
        status, payload = self._request_json("GET", detail_url, access_token)
        if status >= 400:
            raise GoogleOpsError(f"Gmail read failed ({status}): {payload}")

        payload_obj = payload.get("payload")
        headers = payload_obj.get("headers") if isinstance(payload_obj, dict) else None
        from_value = self._header_value(headers, "From") or "(unknown)"
        subject = self._header_value(headers, "Subject") or "(no subject)"
        date_value = self._header_value(headers, "Date") or "(unknown date)"
        snippet = str(payload.get("snippet", "")).strip()
        return GmailMessageSummary(
            message_id=normalized_id,
            from_value=from_value,
            subject=subject,
            date=date_value,
            snippet=snippet,
        )

    def gmail_send_message(self, to_email: str, subject: str, body_text: str) -> str:
        to_value = to_email.strip()
        subject_value = subject.strip()
        body_value = body_text.strip()
        if not to_value or "@" not in to_value:
            raise GoogleOpsError("Valid recipient email is required")
        if not subject_value:
            raise GoogleOpsError("Email subject is required")
        if not body_value:
            raise GoogleOpsError("Email body is required")

        message = EmailMessage()
        message["To"] = to_value
        message["Subject"] = subject_value
        message.set_content(body_value)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8").rstrip("=")

        access_token = self._refresh_access_token()
        status, payload = self._request_json(
            "POST",
            GMAIL_SEND_ENDPOINT,
            access_token,
            body={"raw": raw},
        )
        if status >= 400:
            raise GoogleOpsError(f"Gmail send failed ({status}): {payload}")
        message_id = str(payload.get("id", "")).strip()
        if not message_id:
            raise GoogleOpsError("Gmail send succeeded but response had no message id")
        return message_id

    def _timezone(self) -> timezone:
        if ZoneInfo is None:
            return timezone.utc
        try:
            return ZoneInfo(self.default_timezone)
        except Exception:
            return timezone.utc

    def _parse_datetime(self, raw_value: str) -> datetime:
        candidate = raw_value.strip()
        if not candidate:
            raise GoogleOpsError("Datetime value is required")
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise GoogleOpsError(
                "Invalid datetime format. Use ISO like 2026-03-01T17:30 or 2026-03-01T17:30+10:00"
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self._timezone())
        return parsed

    def calendar_list_events(self, days: int, limit: int) -> List[CalendarEventSummary]:
        days_value = max(1, min(days, 30))
        limit_value = max(1, min(limit, 50))
        now_utc = datetime.now(timezone.utc)
        time_min = urllib.parse.quote(now_utc.isoformat())
        time_max = urllib.parse.quote((now_utc + timedelta(days=days_value)).isoformat())

        access_token = self._refresh_access_token()
        endpoint = CALENDAR_EVENTS_ENDPOINT.format(calendar_id="primary")
        url = (
            f"{endpoint}?singleEvents=true&orderBy=startTime"
            f"&timeMin={time_min}&timeMax={time_max}&maxResults={limit_value}"
        )
        status, payload = self._request_json("GET", url, access_token)
        if status >= 400:
            raise GoogleOpsError(f"Calendar list failed ({status}): {payload}")

        items = payload.get("items")
        if not isinstance(items, list):
            return []

        events: List[CalendarEventSummary] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("id", "")).strip()
            summary = str(item.get("summary", "")).strip() or "(no title)"
            start_obj = item.get("start")
            end_obj = item.get("end")
            start_value = ""
            end_value = ""
            if isinstance(start_obj, dict):
                start_value = str(start_obj.get("dateTime") or start_obj.get("date") or "").strip()
            if isinstance(end_obj, dict):
                end_value = str(end_obj.get("dateTime") or end_obj.get("date") or "").strip()
            html_link = str(item.get("htmlLink", "")).strip()
            if not event_id:
                continue
            events.append(
                CalendarEventSummary(
                    event_id=event_id,
                    summary=summary,
                    start=start_value,
                    end=end_value,
                    html_link=html_link,
                )
            )
            if len(events) >= limit_value:
                break
        return events

    def calendar_today_events(self, limit: int) -> List[CalendarEventSummary]:
        tz = self._timezone()
        now_local = datetime.now(tz)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)

        access_token = self._refresh_access_token()
        endpoint = CALENDAR_EVENTS_ENDPOINT.format(calendar_id="primary")
        url = (
            f"{endpoint}?singleEvents=true&orderBy=startTime"
            f"&timeMin={urllib.parse.quote(start_local.astimezone(timezone.utc).isoformat())}"
            f"&timeMax={urllib.parse.quote(end_local.astimezone(timezone.utc).isoformat())}"
            f"&maxResults={max(1, min(limit, 50))}"
        )
        status, payload = self._request_json("GET", url, access_token)
        if status >= 400:
            raise GoogleOpsError(f"Calendar today failed ({status}): {payload}")

        items = payload.get("items")
        if not isinstance(items, list):
            return []

        events: List[CalendarEventSummary] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("id", "")).strip()
            if not event_id:
                continue
            summary = str(item.get("summary", "")).strip() or "(no title)"
            start_obj = item.get("start")
            end_obj = item.get("end")
            start_value = ""
            end_value = ""
            if isinstance(start_obj, dict):
                start_value = str(start_obj.get("dateTime") or start_obj.get("date") or "").strip()
            if isinstance(end_obj, dict):
                end_value = str(end_obj.get("dateTime") or end_obj.get("date") or "").strip()
            html_link = str(item.get("htmlLink", "")).strip()
            events.append(
                CalendarEventSummary(
                    event_id=event_id,
                    summary=summary,
                    start=start_value,
                    end=end_value,
                    html_link=html_link,
                )
            )
        return events

    def calendar_create_event(
        self,
        title: str,
        start_iso: str,
        end_iso: str,
        description: str,
    ) -> CalendarEventSummary:
        title_value = title.strip()
        if not title_value:
            raise GoogleOpsError("Event title is required")

        start_dt = self._parse_datetime(start_iso)
        end_dt = self._parse_datetime(end_iso)
        if end_dt <= start_dt:
            raise GoogleOpsError("Event end must be after event start")

        payload = {
            "summary": title_value,
            "description": description.strip(),
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": self.default_timezone,
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": self.default_timezone,
            },
        }
        access_token = self._refresh_access_token()
        endpoint = CALENDAR_EVENTS_ENDPOINT.format(calendar_id="primary")
        status, response = self._request_json("POST", endpoint, access_token, body=payload)
        if status >= 400:
            raise GoogleOpsError(f"Calendar create failed ({status}): {response}")

        event_id = str(response.get("id", "")).strip()
        summary = str(response.get("summary", "")).strip() or title_value
        html_link = str(response.get("htmlLink", "")).strip()
        start_obj = response.get("start")
        end_obj = response.get("end")
        start_value = ""
        end_value = ""
        if isinstance(start_obj, dict):
            start_value = str(start_obj.get("dateTime") or start_obj.get("date") or "").strip()
        if isinstance(end_obj, dict):
            end_value = str(end_obj.get("dateTime") or end_obj.get("date") or "").strip()

        if not event_id:
            raise GoogleOpsError("Calendar create succeeded but response had no event id")

        return CalendarEventSummary(
            event_id=event_id,
            summary=summary,
            start=start_value,
            end=end_value,
            html_link=html_link,
        )
