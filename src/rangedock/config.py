"""Host-side RangeDock files: where they live, how they are read, and how they are written."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10 only
    import tomli as tomllib

from .core import RangeDockError


def config_dir() -> Path:
    """Return the per-user RangeDock directory without creating it."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        return (Path(appdata) if appdata else Path.home() / "AppData" / "Roaming") / "RangeDock"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".config"
    return base / "rangedock"


def read_toml(path: Path) -> dict:
    """Parse a TOML file, treating a missing file as empty."""
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as exc:
        raise RangeDockError(f"Invalid TOML in {path}: {exc}") from exc
    except OSError as exc:
        raise RangeDockError(f"Cannot read {path}: {exc}") from exc


def write_private_text(path: Path, text: str) -> None:
    """Atomically replace a file that only the current user can read where permissions apply."""
    temporary = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
        raise RangeDockError(f"Cannot write {path}: {exc}") from exc


def create_private_file(path: Path) -> None:
    """Create an empty file readable only by the current user if it does not exist yet."""
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600))
    except OSError as exc:
        raise RangeDockError(f"Cannot create {path}: {exc}") from exc


def toml_string(value: str) -> str:
    """Encode a TOML basic string."""
    escapes = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}
    encoded = []
    for char in value:
        if char in escapes:
            encoded.append(escapes[char])
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            encoded.append(f"\\u{ord(char):04x}")
        else:
            encoded.append(char)
    return f'"{"".join(encoded)}"'
