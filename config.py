from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Config:
    server_url: str
    server_token: str
    playback_device: str
    touch_gpio: int
    touch_active_high: bool
    command_timeout_seconds: int
    http_retries: int
    lens_position: str  # để trống = lấy nét tự động như code cũ

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        values = _read_env(path or Path(__file__).with_name(".env"))
        values.update(os.environ)

        server_url = _required(values, "MAC_SERVER_URL").rstrip("/")
        if not server_url.startswith(("http://", "https://")):
            raise ConfigError("MAC_SERVER_URL phải bắt đầu bằng http:// hoặc https://")

        return cls(
            server_url=server_url,
            server_token=_required(values, "SERVER_TOKEN"),
            playback_device=values.get("ONBOARD_PLAYBACK_DEVICE", "default").strip() or "default",
            touch_gpio=_integer(values, "TOUCH_GPIO", 25, minimum=0, maximum=27),
            touch_active_high=_bool(values, "TOUCH_ACTIVE_HIGH", True),
            command_timeout_seconds=_integer(values, "COMMAND_TIMEOUT_SECONDS", 60, minimum=1),
            http_retries=_integer(values, "HTTP_RETRIES", 2, minimum=0),
            lens_position=values.get("LENS_POSITION", "").strip(),
        )


def _read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not key:
            raise ConfigError(f"Dòng .env không hợp lệ: {raw_line}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def _required(values: dict[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ConfigError(f"Thiếu cấu hình bắt buộc: {key}")
    return value


def _integer(values: dict[str, str], key: str, default: int, *, minimum: int, maximum: int | None = None) -> int:
    raw = values.get(key, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(f"{key} không phải số nguyên: {raw}") from error
    if value < minimum or (maximum is not None and value > maximum):
        limit = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise ConfigError(f"{key} phải nằm trong khoảng {limit}: {raw}")
    return value


def _bool(values: dict[str, str], key: str, default: bool) -> bool:
    raw = values.get(key, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{key} không phải giá trị đúng/sai: {raw}")
