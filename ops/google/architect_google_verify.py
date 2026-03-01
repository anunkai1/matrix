#!/usr/bin/env python3
"""Refresh Architect Google OAuth access token and verify Gmail + Calendar API access."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GMAIL_PROFILE_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
CALENDAR_LIST_ENDPOINT = "https://www.googleapis.com/calendar/v3/users/me/calendarList?maxResults=10"
DEFAULT_CLIENT_SECRET_PATH = Path("~/.config/google/architect/client_secret.json").expanduser()
DEFAULT_TOKEN_PATH = Path("~/.config/google/architect/oauth_token.json").expanduser()


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_json_bytes(payload: bytes) -> Dict[str, Any]:
    text = payload.decode("utf-8", errors="replace")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise RuntimeError("Expected JSON object response")
    return parsed


def post_form(url: str, fields: Dict[str, str], timeout: int = 30) -> Tuple[int, Dict[str, Any]]:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        status = exc.code
    return status, parse_json_bytes(payload)


def get_json(url: str, access_token: str, timeout: int = 30) -> Tuple[int, Dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        status = exc.code
    return status, parse_json_bytes(payload)


def load_client_credentials(path: Path) -> Dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("Client secret JSON is invalid")
    root = data.get("installed") or data.get("web") or data
    if not isinstance(root, dict):
        raise RuntimeError("Client secret JSON is missing 'installed'/'web' object")
    client_id = str(root.get("client_id", "")).strip()
    client_secret = str(root.get("client_secret", "")).strip()
    if not client_id or not client_secret:
        raise RuntimeError("Client secret JSON missing client_id/client_secret")
    return {"client_id": client_id, "client_secret": client_secret}


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(path)
    os.chmod(path, 0o600)


def refresh_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> Dict[str, Any]:
    status, payload = post_form(
        TOKEN_ENDPOINT,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    if status >= 400 or "access_token" not in payload:
        raise RuntimeError(f"Access-token refresh failed ({status}): {payload}")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client-secret",
        type=Path,
        default=DEFAULT_CLIENT_SECRET_PATH,
        help=f"Path to OAuth client secret JSON (default: {DEFAULT_CLIENT_SECRET_PATH})",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=DEFAULT_TOKEN_PATH,
        help=f"Path to OAuth token JSON (default: {DEFAULT_TOKEN_PATH})",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.client_secret.exists():
        raise RuntimeError(f"Client secret JSON not found: {args.client_secret}")
    if not args.token_file.exists():
        raise RuntimeError(f"Token JSON not found: {args.token_file}")

    creds = load_client_credentials(args.client_secret)
    token_doc = json.loads(args.token_file.read_text(encoding="utf-8"))
    refresh_token = str(token_doc.get("refresh_token", "")).strip()
    if not refresh_token:
        raise RuntimeError("Token file is missing refresh_token")

    refreshed = refresh_access_token(
        creds["client_id"],
        creds["client_secret"],
        refresh_token,
    )
    access_token = str(refreshed["access_token"])

    token_doc.update(refreshed)
    token_doc["refreshed_at_utc"] = now_utc_iso()
    token_doc["token_endpoint"] = TOKEN_ENDPOINT
    atomic_write_json(args.token_file, token_doc)

    gmail_status, gmail = get_json(GMAIL_PROFILE_ENDPOINT, access_token)
    if gmail_status >= 400:
        raise RuntimeError(f"Gmail API verification failed ({gmail_status}): {gmail}")

    cal_status, cal = get_json(CALENDAR_LIST_ENDPOINT, access_token)
    if cal_status >= 400:
        raise RuntimeError(f"Calendar API verification failed ({cal_status}): {cal}")

    cal_items = cal.get("items") if isinstance(cal, dict) else None
    cal_count = len(cal_items) if isinstance(cal_items, list) else 0

    print("Google API verification succeeded")
    print("- Gmail emailAddress:", gmail.get("emailAddress", "<unknown>"))
    print("- Gmail messagesTotal:", gmail.get("messagesTotal", "<unknown>"))
    print("- Calendar list count:", cal_count)
    if isinstance(cal_items, list):
        for item in cal_items[:5]:
            if isinstance(item, dict):
                summary = str(item.get("summary", "")).strip() or "<no-summary>"
                cal_id = str(item.get("id", "")).strip() or "<no-id>"
                print(f"  - {summary} ({cal_id})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
