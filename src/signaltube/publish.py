from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BASE_URL = "https://mavali.top/upload/"
DEFAULT_PUBLIC_BASE_URL = "https://mavali.top/projects/"
DEFAULT_REMOTE_DIR = "SignalTube"
DEFAULT_REMOTE_NAME = "index.html"
DEFAULT_PLAYWRIGHT_PYTHON = Path("/var/lib/server3-browser-brain/venv/bin/python")
ROOT = Path(__file__).resolve().parents[2]
HELPER_SCRIPT = ROOT / "ops" / "signaltube_publish_filegator.py"


class SignalTubePublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileGatorPublishConfig:
    base_url: str
    public_base_url: str
    username: str
    password: str
    remote_dir: str
    remote_name: str
    playwright_python: Path

    @property
    def public_url(self) -> str:
        return (
            self.public_base_url.rstrip("/")
            + "/"
            + self.remote_dir.strip("/")
            + "/"
            + self.remote_name.strip("/")
        )


def build_publish_config(
    *,
    username: str | None = None,
    password: str | None = None,
    base_url: str | None = None,
    public_base_url: str | None = None,
    remote_dir: str | None = None,
    remote_name: str | None = None,
    playwright_python: Path | None = None,
) -> FileGatorPublishConfig | None:
    resolved_username = (username or os.environ.get("SIGNALTUBE_PUBLISH_USERNAME", "")).strip()
    resolved_password = password or os.environ.get("SIGNALTUBE_PUBLISH_PASSWORD", "")
    if not resolved_username or not resolved_password:
        return None
    resolved_python = Path(
        playwright_python
        or os.environ.get("SIGNALTUBE_PUBLISH_PLAYWRIGHT_PYTHON", str(DEFAULT_PLAYWRIGHT_PYTHON))
    )
    return FileGatorPublishConfig(
        base_url=(base_url or os.environ.get("SIGNALTUBE_PUBLISH_BASE_URL", DEFAULT_BASE_URL)).strip(),
        public_base_url=(
            public_base_url or os.environ.get("SIGNALTUBE_PUBLISH_PUBLIC_BASE_URL", DEFAULT_PUBLIC_BASE_URL)
        ).strip(),
        username=resolved_username,
        password=resolved_password,
        remote_dir=(remote_dir or os.environ.get("SIGNALTUBE_PUBLISH_REMOTE_DIR", DEFAULT_REMOTE_DIR)).strip("/"),
        remote_name=(remote_name or os.environ.get("SIGNALTUBE_PUBLISH_REMOTE_NAME", DEFAULT_REMOTE_NAME)).strip("/"),
        playwright_python=resolved_python,
    )


def publish_html(html_path: Path, config: FileGatorPublishConfig) -> str:
    html_path = html_path.resolve()
    if not html_path.exists():
        raise SignalTubePublishError(f"html file not found: {html_path}")
    if not config.playwright_python.exists():
        raise SignalTubePublishError(f"playwright python not found: {config.playwright_python}")
    if not HELPER_SCRIPT.exists():
        raise SignalTubePublishError(f"publish helper missing: {HELPER_SCRIPT}")

    with tempfile.TemporaryDirectory(prefix="signaltube-publish-") as tmp:
        staged_path = Path(tmp) / config.remote_name
        shutil.copyfile(html_path, staged_path)
        completed = subprocess.run(
            [
                str(config.playwright_python),
                str(HELPER_SCRIPT),
                "--base-url",
                config.base_url,
                "--username",
                config.username,
                "--password",
                config.password,
                "--remote-dir",
                config.remote_dir,
                "--source-path",
                str(staged_path),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown publish failure").strip()
        raise SignalTubePublishError(detail)
    return config.public_url

