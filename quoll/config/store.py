from __future__ import annotations

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]
from pathlib import Path

import tomli_w

_CONFIG_PATH = Path.home() / ".config" / "quoll" / "config.toml"
# Where tokens were stored before the tool was renamed; read when the new file doesn't exist yet.
_LEGACY_CONFIG_PATH = Path.home() / ".config" / "forge" / "config.toml"


def load_stored_token(platform: str = "github") -> str:
    path = _CONFIG_PATH if _CONFIG_PATH.exists() else _LEGACY_CONFIG_PATH
    if not path.exists():
        return ""
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return data.get(platform, {}).get("token", "")
    except Exception:
        return ""


def save_token(token: str, platform: str = "github") -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, "rb") as f:
                existing = tomllib.load(f)
        except Exception:
            pass
    existing.setdefault(platform, {})["token"] = token
    with open(_CONFIG_PATH, "wb") as f:
        tomli_w.dump(existing, f)
