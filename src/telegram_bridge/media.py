import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Protocol, Tuple


class TelegramFileClientProtocol(Protocol):
    def get_file(self, file_id: str) -> Dict[str, object]:
        ...

    def download_file_to_path(
        self,
        file_path: str,
        target_path: str,
        max_bytes: int,
        size_label: str = "File",
    ) -> None:
        ...


@dataclass(frozen=True)
class TelegramFileDownloadSpec:
    file_id: str
    max_bytes: int
    size_label: str
    temp_prefix: str
    default_suffix: str
    too_large_label: str
    suffix_hint: str = ""


def download_telegram_file_to_temp(
    client: TelegramFileClientProtocol,
    spec: TelegramFileDownloadSpec,
) -> Tuple[str, int]:
    file_meta = client.get_file(spec.file_id)
    file_path = file_meta.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        raise RuntimeError("Telegram getFile response missing file_path")

    file_size = file_meta.get("file_size")
    if isinstance(file_size, int) and file_size > spec.max_bytes:
        raise ValueError(
            f"{spec.too_large_label} too large ({file_size} bytes). Max is {spec.max_bytes} bytes."
        )

    suffix = Path(spec.suffix_hint).suffix if spec.suffix_hint else ""
    if not suffix:
        suffix = Path(file_path).suffix or spec.default_suffix

    fd, tmp_path = tempfile.mkstemp(prefix=spec.temp_prefix, suffix=suffix)
    os.close(fd)
    try:
        client.download_file_to_path(
            file_path,
            tmp_path,
            spec.max_bytes,
            size_label=spec.size_label,
        )
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

    final_size = file_size if isinstance(file_size, int) else os.path.getsize(tmp_path)
    return tmp_path, final_size
