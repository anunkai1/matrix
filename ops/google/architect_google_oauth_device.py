#!/usr/bin/env python3
"""Obtain Google OAuth tokens for Architect using device authorization flow."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

DEVICE_CODE_ENDPOINT = "https://oauth2.googleapis.com/device/code"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
DEFAULT_CLIENT_SECRET_PATH = Path("~/.config/google/architect/client_secret.json").expanduser()
DEFAULT_TOKEN_PATH = Path("~/.config/google/architect/oauth_token.json").expanduser()
DEFAULT_SCOPES = [
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/calendar",
]


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_json_bytes(payload: bytes) -> Dict[str, Any]:
    text = payload.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(f"Expected JSON response, got: {text[:500]}")
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
    parsed = parse_json_bytes(payload)
    return status, parsed


def load_client_credentials(path: Path) -> Dict[str, str]:
    if not path.exists():
        raise RuntimeError(
            f"Client secret file not found: {path}. Download OAuth client JSON from Google Cloud and place it there."
        )
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
    return {
        "client_id": client_id,
        "client_secret": client_secret,
    }


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    ensure_parent_dir(path)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(path)
    os.chmod(path, 0o600)


def request_device_code(client_id: str, scopes: list[str]) -> Dict[str, Any]:
    status, payload = post_form(
        DEVICE_CODE_ENDPOINT,
        {
            "client_id": client_id,
            "scope": " ".join(scopes),
        },
    )
    if status >= 400:
        raise RuntimeError(f"Device code request failed ({status}): {payload}")
    required = ("device_code", "user_code")
    missing = [key for key in required if key not in payload]
    if missing:
        raise RuntimeError(f"Device code response missing fields: {', '.join(missing)}")
    return payload


def poll_for_tokens(
    client_id: str,
    client_secret: str,
    device_code: str,
    interval_seconds: int,
    timeout_seconds: int,
) -> Dict[str, Any]:
    start = time.time()
    interval = max(interval_seconds, 1)

    while True:
        if time.time() - start > timeout_seconds:
            raise RuntimeError("Timed out waiting for OAuth approval")
        time.sleep(interval)
        status, payload = post_form(
            TOKEN_ENDPOINT,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )

        error_code = str(payload.get("error", "")).strip()
        if status < 400 and "access_token" in payload:
            return payload

        if error_code == "authorization_pending":
            continue
        if error_code == "slow_down":
            interval += 5
            continue
        if error_code in {"access_denied", "expired_token"}:
            raise RuntimeError(f"OAuth flow ended with error: {error_code}")

        raise RuntimeError(f"Token request failed ({status}): {payload}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client-secret",
        type=Path,
        default=DEFAULT_CLIENT_SECRET_PATH,
        help=f"Path to OAuth client secret JSON (default: {DEFAULT_CLIENT_SECRET_PATH})",
    )
    parser.add_argument(
        "--token-out",
        type=Path,
        default=DEFAULT_TOKEN_PATH,
        help=f"Path to write OAuth token JSON (default: {DEFAULT_TOKEN_PATH})",
    )
    parser.add_argument(
        "--scope",
        action="append",
        default=[],
        help="Google OAuth scope. Repeat for multiple scopes. Defaults to full Gmail + Calendar scopes.",
    )
    parser.add_argument(
        "--poll-timeout-seconds",
        type=int,
        default=900,
        help="How long to wait for user approval before timing out (default: 900)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    scopes = args.scope or list(DEFAULT_SCOPES)
    creds = load_client_credentials(args.client_secret)

    print("Requesting Google device authorization...")
    device = request_device_code(creds["client_id"], scopes)

    verification_url = str(device.get("verification_url", "https://www.google.com/device")).strip()
    verification_url_complete = str(device.get("verification_url_complete", "")).strip()
    user_code = str(device["user_code"])
    device_code = str(device["device_code"])
    interval = int(device.get("interval", 5))

    print("\nComplete this step in your browser:")
    print(f"- Verification URL: {verification_url}")
    if verification_url_complete:
        print(f"- One-click URL: {verification_url_complete}")
    print(f"- User code: {user_code}")
    print("- Login as: vladislavsllm26@gmail.com")
    print("- Grant requested permissions")
    print("\nWaiting for approval...")

    tokens = poll_for_tokens(
        creds["client_id"],
        creds["client_secret"],
        device_code,
        interval,
        args.poll_timeout_seconds,
    )

    token_payload: Dict[str, Any] = dict(tokens)
    token_payload["obtained_at_utc"] = now_utc_iso()
    token_payload["scopes"] = scopes
    token_payload["token_endpoint"] = TOKEN_ENDPOINT

    atomic_write_json(args.token_out, token_payload)
    print("\nOAuth token written:", args.token_out)
    if "refresh_token" not in token_payload:
        print(
            "Warning: no refresh_token returned. Re-run with a newly revoked grant or force consent in Google settings.",
            file=sys.stderr,
        )
    else:
        print("Refresh token present: yes")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
