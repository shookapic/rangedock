"""Persisted user preferences stored in config.toml next to the VPN profiles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import config_dir, read_toml, toml_string, write_private_text
from .core import RangeDockError

Value = bool | str
TRUE_WORDS = ("true", "yes", "on", "1")
FALSE_WORDS = ("false", "no", "off", "0")
HEADER = "# RangeDock preferences. Edit here or with 'rangedock config set KEY VALUE'.\n"


@dataclass(frozen=True)
class Setting:
    key: str
    default: Value
    help: str
    choices: tuple[str, ...] = ()

    def parse(self, raw: str) -> Value:
        if isinstance(self.default, bool):
            word = raw.strip().lower()
            if word in TRUE_WORDS or word in FALSE_WORDS:
                return word in TRUE_WORDS
            raise RangeDockError(f"{self.key} must be true or false.")
        if raw not in self.choices:
            raise RangeDockError(f"{self.key} must be one of: {', '.join(self.choices)}")
        return raw

    def check(self, value: object, path: Path) -> Value:
        if isinstance(self.default, bool) and isinstance(value, bool):
            return value
        if isinstance(self.default, str) and value in self.choices:
            return value
        expected = "true or false" if isinstance(self.default, bool) else f"one of {', '.join(self.choices)}"
        raise RangeDockError(f"Invalid setting in {path}: {self.key} must be {expected}.")


SETTINGS = {
    setting.key: setting
    for setting in (
        Setting("console.history", True, "save console history on the host"),
        Setting("console.plain", False, "always use the simple line prompt (no menus, colors, or symbols)"),
        Setting("console.color", True, "use colors in the full console (NO_COLOR also disables them)"),
        Setting("console.editing", "emacs", "line editing key bindings", ("emacs", "vi")),
        Setting("desktop.open_browser", True, "open the browser when a desktop is ready"),
    )
}


def format_value(value: Value) -> str:
    return str(value).lower() if isinstance(value, bool) else value


class Preferences:
    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "config.toml"

    def values(self) -> dict[str, Value]:
        """Every known setting, with stored values replacing defaults."""
        return {key: setting.default for key, setting in SETTINGS.items()} | self._stored()

    def get(self, key: str) -> Value:
        self._setting(key)
        return self.values()[key]

    def set(self, key: str, raw: str) -> Value:
        value = self._setting(key).parse(raw)
        stored = self._stored()
        stored[key] = value
        self._save(stored)
        return value

    def reset(self, key: str) -> Value:
        setting = self._setting(key)
        stored = self._stored()
        if stored.pop(key, None) is not None:
            self._save(stored)
        return setting.default

    @staticmethod
    def _setting(key: str) -> Setting:
        if key not in SETTINGS:
            raise RangeDockError(f"Unknown setting '{key}'. Known settings: {', '.join(SETTINGS)}")
        return SETTINGS[key]

    def _stored(self) -> dict[str, Value]:
        stored = {}
        for section, entries in read_toml(self.path).items():
            if not isinstance(entries, dict):
                raise RangeDockError(f"Invalid setting in {self.path}: '{section}' must be a table.")
            for name, value in entries.items():
                key = f"{section}.{name}"
                if key not in SETTINGS:
                    raise RangeDockError(f"Unknown setting '{key}' in {self.path}.")
                stored[key] = SETTINGS[key].check(value, self.path)
        return stored

    def _save(self, stored: dict[str, Value]) -> None:
        sections: dict[str, list[str]] = {}
        for key in SETTINGS:
            if key in stored:
                section, name = key.split(".", 1)
                value = stored[key]
                encoded = format_value(value) if isinstance(value, bool) else toml_string(value)
                sections.setdefault(section, []).append(f"{name} = {encoded}\n")
        blocks = [HEADER, *(f"[{section}]\n{''.join(lines)}" for section, lines in sections.items())]
        write_private_text(self.path, "\n".join(blocks))
