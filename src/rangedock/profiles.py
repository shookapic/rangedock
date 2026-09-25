"""Named VPN profiles: remembered host paths, never copies of key material."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import config_dir, read_toml, toml_string, write_private_text
from .core import NAME_RE, RangeDockError, resolve_vpn_config, valid_name

VPN_TYPES = ("openvpn",)
HEADER = "# Managed by 'rangedock vpn profile'. Stores paths only; keys stay in their own files.\n"


@dataclass(frozen=True)
class VpnProfile:
    name: str
    type: str
    config: Path

    @property
    def config_dir(self) -> Path:
        return self.config.parent

    @property
    def available(self) -> bool:
        return self.config.is_file()


class ProfileStore:
    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "profiles.toml"

    def list(self) -> list[VpnProfile]:
        return sorted(self._load().values(), key=lambda profile: profile.name)

    def names(self) -> list[str]:
        return [profile.name for profile in self.list()]

    def get(self, name: str) -> VpnProfile:
        profile = self._load().get(name)
        if profile is None:
            raise self._missing(name)
        return profile

    def resolve(self, name: str) -> VpnProfile:
        """Return a profile whose config can be mounted right now."""
        profile = self.get(name)
        try:
            resolve_vpn_config(profile.config)
        except RangeDockError as exc:
            raise RangeDockError(f"VPN profile '{name}' cannot be used: {exc}") from exc
        return profile

    def add(self, name: str, config: Path, vpn_type: str = "openvpn") -> VpnProfile:
        valid_name(name)
        if vpn_type not in VPN_TYPES:
            raise RangeDockError(f"VPN type must be one of: {', '.join(VPN_TYPES)}")
        profile = VpnProfile(name, vpn_type, resolve_vpn_config(config))
        profiles = self._load()
        if name in profiles:
            raise RangeDockError(
                f"VPN profile '{name}' already exists. Remove it first with 'rangedock vpn profile remove {name}'."
            )
        profiles[name] = profile
        self._save(profiles)
        return profile

    def remove(self, name: str) -> VpnProfile:
        """Forget a profile. The files it points to are never touched."""
        profiles = self._load()
        profile = profiles.pop(name, None)
        if profile is None:
            raise self._missing(name)
        self._save(profiles)
        return profile

    @staticmethod
    def _missing(name: str) -> RangeDockError:
        return RangeDockError(
            f"VPN profile '{name}' does not exist. Add it with 'rangedock vpn profile add {name} --config FILE'."
        )

    def _load(self) -> dict[str, VpnProfile]:
        section = read_toml(self.path).get("vpn", {})
        if not isinstance(section, dict):
            raise RangeDockError(f"Invalid profile file {self.path}: 'vpn' must be a table.")
        profiles = {}
        for name, entry in section.items():
            if not NAME_RE.fullmatch(name):
                raise RangeDockError(f"Invalid profile file {self.path}: bad VPN profile name '{name}'.")
            if not isinstance(entry, dict) or not isinstance(entry.get("config"), str):
                raise RangeDockError(f"Invalid profile file {self.path}: [vpn.{name}] needs a 'config' path.")
            vpn_type = entry.get("type", "openvpn")
            if vpn_type not in VPN_TYPES:
                raise RangeDockError(
                    f"Invalid profile file {self.path}: [vpn.{name}] has unsupported type '{vpn_type}'."
                )
            profiles[name] = VpnProfile(name, vpn_type, Path(entry["config"]))
        return profiles

    def _save(self, profiles: dict[str, VpnProfile]) -> None:
        blocks = [HEADER]
        for profile in sorted(profiles.values(), key=lambda item: item.name):
            blocks.append(
                f"[vpn.{profile.name}]\n"
                f"type = {toml_string(profile.type)}\n"
                f"config = {toml_string(profile.config.as_posix())}\n"
                f"config_dir = {toml_string(profile.config_dir.as_posix())}\n"
            )
        write_private_text(self.path, "\n".join(blocks))
