"""Docker lifecycle with explicit ownership and no shell interpolation."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from importlib import resources
from pathlib import Path

IMAGE_VERSION = "0.4.0"
PROFILES = ("base", "web", "desktop")
IMAGES = {profile: f"rangedock:{IMAGE_VERSION}-{profile}" for profile in PROFILES}
REMOTE_IMAGES = {profile: f"ghcr.io/shookapic/rangedock:v{IMAGE_VERSION}-{profile}" for profile in PROFILES}
IMAGE = IMAGES["web"]
LABEL = "dev.rangedock.managed"
WORKSPACE_LABEL = "dev.rangedock.workspace"
PROFILE_LABEL = "dev.rangedock.profile"
VPN_LABEL = "dev.rangedock.vpn"
VPN_PROFILE_LABEL = "dev.rangedock.vpn-profile"
VPN_SUFFIXES = (".ovpn", ".conf")
VPN_PID = "/run/rangedock-openvpn.pid"
VPN_LOG = "/run/rangedock-openvpn.log"
VPN_DISABLED = "/run/rangedock-vpn-disabled"
# OpenVPN logs this once the tunnel is up, and "process restarting" when it drops and retries.
VPN_CONNECTED = "Initialization Sequence Completed"
VPN_RESTARTING = "process restarting"
VPN_CONNECT_TIMEOUT = 15.0
VPN_MESSAGES = {
    "workspace stopped": "workspace stopped",
    "stopped": "OpenVPN stopped",
    "connecting": "OpenVPN running, tunnel not up yet",
    "connected": "OpenVPN connected",
}
NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,39}\Z")


class RangeDockError(Exception):
    """An actionable CLI error."""


class Docker:
    def call(self, args: list[str], *, input_text: str | None = None,
             interactive: bool = False) -> str:
        command = ["docker", *args]
        try:
            result = subprocess.run(
                command, input=input_text, text=True, encoding="utf-8", check=False,
                stdout=None if interactive else subprocess.PIPE,
                stderr=None if interactive else subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RangeDockError("Docker CLI not found. Install Docker Desktop or Docker Engine.") from exc
        if result.returncode:
            detail = (result.stderr or "").strip() if not interactive else ""
            raise RangeDockError(detail or f"Docker command failed with exit code {result.returncode}")
        return (result.stdout or "").strip()

    def status(self, args: list[str]) -> int:
        """Run an interactive Docker command and return its exit code instead of raising."""
        try:
            return subprocess.run(["docker", *args], check=False).returncode
        except FileNotFoundError as exc:
            raise RangeDockError("Docker CLI not found. Install Docker Desktop or Docker Engine.") from exc


def valid_name(name: str) -> str:
    if not NAME_RE.fullmatch(name):
        raise RangeDockError("Name must start with a lowercase letter and contain only a-z, 0-9, or - (max 40).")
    return name


def container_name(name: str) -> str:
    return f"rangedock-{valid_name(name)}"


def valid_profile(profile: str) -> str:
    if profile not in PROFILES:
        raise RangeDockError(f"Image must be one of: {', '.join(PROFILES)}")
    return profile


def resolve_vpn_config(path: Path) -> Path:
    config = path.expanduser().resolve()
    if not config.is_file():
        raise RangeDockError(f"VPN config not found: {config}")
    if config.suffix.lower() not in VPN_SUFFIXES:
        raise RangeDockError(f"VPN config must be an OpenVPN .ovpn or .conf file: {config}")
    if "," in str(config.parent):
        raise RangeDockError("VPN directory path cannot contain a comma (Docker mount syntax).")
    return config


def tty_flags() -> str:
    return "-it" if sys.stdin.isatty() and sys.stdout.isatty() else "-i"


def host_user_options() -> list[str]:
    # A Linux/macOS bind mount keeps host ownership. Match that identity so
    # files created inside /workspace belong to the person running the CLI.
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        return ["--user", f"{os.getuid()}:{os.getgid()}", "--env", "HOME=/workspace"]
    return []


class Workbench:
    def __init__(self, docker: Docker | None = None):
        self.docker = docker or Docker()

    def daemon(self) -> str:
        try:
            return self.docker.call(["version", "--format", "{{.Server.Version}}"])
        except RangeDockError as exc:
            raise RangeDockError(f"Docker daemon is unavailable. Start Docker, then retry. ({exc})") from exc

    def linux_daemon(self) -> str:
        version = self.daemon()
        platform = self.docker.call(["info", "--format", "{{.OSType}}"])
        if platform == "windows":
            raise RangeDockError("Docker is running Windows containers. Switch Docker Desktop to Linux containers.")
        if platform != "linux":
            raise RangeDockError(f"Docker reported unsupported container OS: {platform or 'unknown'}.")
        return version

    def image_exists(self, profile: str = "web") -> bool:
        try:
            self.docker.call(["image", "inspect", IMAGES[valid_profile(profile)], "--format", "{{.Id}}"])
            return True
        except RangeDockError:
            return False

    def build(self, profile: str = "web") -> None:
        self.linux_daemon()
        profile = valid_profile(profile)
        context = resources.files("rangedock")
        self.docker.call(["build", "--pull", "--target", profile, "-t", IMAGES[profile], str(context)],
                         interactive=True)

    def pull(self, profile: str = "web") -> None:
        self.linux_daemon()
        profile = valid_profile(profile)
        self.docker.call(["pull", REMOTE_IMAGES[profile]], interactive=True)
        self.docker.call(["tag", REMOTE_IMAGES[profile], IMAGES[profile]])

    def _managed(self, name: str) -> tuple[str, dict]:
        container = container_name(name)
        try:
            payload = self.docker.call(["container", "inspect", container, "--format", "{{json .}}"])
            details = json.loads(payload)
        except RangeDockError as exc:
            if "No such container" in str(exc) or "No such object" in str(exc):
                raise RangeDockError(f"Workspace '{name}' does not exist. Open it with 'rangedock open {name}'.") from exc
            raise RangeDockError(f"Cannot inspect workspace '{name}': {exc}") from exc
        except ValueError as exc:
            raise RangeDockError(f"Docker returned invalid details for workspace '{name}'.") from exc
        labels = details.get("Config", {}).get("Labels") or {}
        if labels.get(LABEL) != "true":
            raise RangeDockError(f"Container '{container}' is not managed by RangeDock.")
        return container, details

    def container_exists(self, name: str) -> bool:
        container = container_name(name)
        output = self.docker.call([
            "container", "ls", "-a", "--filter", f"name=^/{container}$", "--format", "{{.Names}}"
        ])
        return container in output.splitlines()

    def create(self, name: str, workspace: Path | None = None, *,
               profile: str = "web", vpn: Path | None = None,
               vpn_profile: str | None = None) -> Path:
        container = container_name(name)
        profile = valid_profile(profile)
        if vpn_profile is not None and vpn is None:
            raise RangeDockError("A VPN profile name needs its config path.")
        config = resolve_vpn_config(vpn) if vpn is not None else None
        self.linux_daemon()
        if self.container_exists(name):
            raise RangeDockError(f"Container '{container}' already exists. Use 'rangedock open {name}' or another name.")
        if not self.image_exists(profile):
            try:
                self.pull(profile)
            except RangeDockError as exc:
                raise RangeDockError(
                    f"Image {IMAGES[profile]} is missing and pull failed. "
                    f"Run 'rangedock build {profile}' to build locally. ({exc})"
                ) from exc
        folder = (workspace or Path.home() / "rangedock-workspaces" / name).expanduser().resolve()
        if "," in str(folder):
            raise RangeDockError("Workspace path cannot contain a comma (Docker mount syntax).")
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RangeDockError(f"Cannot create workspace folder {folder}: {exc}") from exc
        if not folder.is_dir():
            raise RangeDockError(f"Workspace path is not a directory: {folder}")
        vpn_options = []
        if config is not None:
            vpn_options = [
                "--label", f"{VPN_LABEL}={config}",
                "--mount", f"type=bind,source={config.parent},target=/vpn,readonly",
                "--cap-add", "NET_ADMIN", "--device", "/dev/net/tun:/dev/net/tun",
            ]
            if vpn_profile is not None:
                vpn_options += ["--label", f"{VPN_PROFILE_LABEL}={vpn_profile}"]
        desktop_options = ["--publish", "127.0.0.1::6080"] if profile == "desktop" else []
        self.docker.call([
            "container", "create", "--name", container,
            "--label", f"{LABEL}=true",
            "--label", f"{WORKSPACE_LABEL}={folder}",
            "--label", f"{PROFILE_LABEL}={profile}",
            "--init", "--security-opt", "no-new-privileges",
            "--mount", f"type=bind,source={folder},target=/workspace",
            *vpn_options, *desktop_options,
            "--workdir", "/workspace", *host_user_options(), IMAGES[profile],
        ])
        return folder

    def open(self, name: str, workspace: Path | None = None, *,
             profile: str | None = None, vpn: Path | None = None,
             vpn_profile: str | None = None) -> None:
        if self.container_exists(name):
            existing = self.info(name)
            if workspace is not None and workspace.expanduser().resolve() != Path(existing["workspace"]):
                raise RangeDockError(
                    f"Workspace '{name}' already uses {existing['workspace']}. Choose another name or omit --workspace."
                )
            if profile is not None and profile != existing["profile"]:
                raise RangeDockError(f"Workspace '{name}' already uses image profile {existing['profile']}.")
            if vpn is not None and str(vpn.expanduser().resolve()) != existing["vpn"]:
                raise RangeDockError(f"Workspace '{name}' already uses VPN config {existing['vpn']}.")
        else:
            self.create(name, workspace, profile=profile or "web", vpn=vpn, vpn_profile=vpn_profile)
        self.enter(name)

    def info(self, name: str) -> dict[str, str]:
        _, details = self._managed(name)
        labels = details.get("Config", {}).get("Labels") or {}
        state = details.get("State", {})
        return {
            "name": name,
            "status": state.get("Status") or ("running" if state.get("Running") else "stopped"),
            "image": details.get("Config", {}).get("Image", "unknown"),
            "image_id": details.get("Image", "unknown"),
            "profile": labels.get(PROFILE_LABEL, "legacy"),
            "workspace": labels.get(WORKSPACE_LABEL, "unknown"),
            "vpn": labels.get(VPN_LABEL, "none"),
            "vpn_profile": labels.get(VPN_PROFILE_LABEL, "none"),
            "created": details.get("Created", "unknown"),
        }

    def _vpn_running(self, container: str) -> bool:
        try:
            pid = self.docker.call(["container", "exec", "--user", "root", container, "cat", VPN_PID])
            if not pid.isdecimal():
                return False
            self.docker.call(["container", "exec", "--user", "root", container,
                              "python3", "-c",
                              "import os,sys; p=int(sys.argv[1]); os.kill(p, 0); "
                              "sys.exit(0 if open(f'/proc/{p}/comm').read().strip() == 'openvpn' else 1)", pid])
            return True
        except RangeDockError:
            return False

    def _reset_vpn(self, container: str, details: dict) -> None:
        if (details.get("Config", {}).get("Labels") or {}).get(VPN_LABEL):
            self.docker.call(["container", "exec", "--user", "root", container,
                              "rm", "-f", VPN_PID, VPN_DISABLED])

    def _start_vpn(self, container: str, details: dict) -> None:
        config = (details.get("Config", {}).get("Labels") or {}).get(VPN_LABEL)
        if not config or self._vpn_running(container):
            return
        try:
            self.docker.call(["container", "exec", "--user", "root", container, "test", "-e", VPN_DISABLED])
            return
        except RangeDockError:
            pass
        try:
            self.docker.call(["container", "exec", "--user", "root", container, "openvpn",
                              "--daemon", "rangedock-vpn", "--cd", "/vpn",
                              "--config", f"/vpn/{Path(config).name}",
                              "--writepid", VPN_PID, "--log", VPN_LOG])
        except RangeDockError as exc:
            raise RangeDockError(f"OpenVPN failed in '{container}'. Run 'rangedock vpn logs {container.removeprefix('rangedock-')}'.") from exc
        for _ in range(5):
            if self._vpn_running(container):
                return
            time.sleep(0.2)
        raise RangeDockError(f"OpenVPN did not start in '{container}'. Run 'rangedock vpn logs {container.removeprefix('rangedock-')}'.")

    def start(self, name: str) -> bool:
        container, details = self._managed(name)
        if details.get("State", {}).get("Running"):
            self._start_vpn(container, details)
            return False
        self.docker.call(["container", "start", container])
        self._reset_vpn(container, details)
        self._start_vpn(container, details)
        return True

    def restart(self, name: str) -> str:
        container, details = self._managed(name)
        if details.get("State", {}).get("Running"):
            self.docker.call(["container", "restart", container])
            self._reset_vpn(container, details)
            self._start_vpn(container, details)
            return "Restarted"
        self.docker.call(["container", "start", container])
        self._reset_vpn(container, details)
        self._start_vpn(container, details)
        return "Started"

    def _vpn_workspace(self, name: str) -> tuple[str, dict]:
        container, details = self._managed(name)
        if not (details.get("Config", {}).get("Labels") or {}).get(VPN_LABEL):
            raise RangeDockError(
                f"Workspace '{name}' has no VPN config. Create one with --vpn FILE or --vpn-profile NAME."
            )
        return container, details

    def vpn_state(self, name: str) -> str:
        """Return 'workspace stopped', 'stopped', 'connecting', or 'connected'."""
        container, details = self._vpn_workspace(name)
        if not details.get("State", {}).get("Running"):
            return "workspace stopped"
        if not self._vpn_running(container):
            return "stopped"
        try:
            last_event = self.docker.call([
                "container", "exec", "--user", "root", container, "sh", "-c", 'grep -E "$1" "$2" | tail -n 1',
                "sh", f"{VPN_CONNECTED}|{VPN_RESTARTING}", VPN_LOG,
            ])
        except RangeDockError:
            return "connecting"
        return "connected" if VPN_CONNECTED in last_event else "connecting"

    def vpn_status(self, name: str) -> str:
        message = VPN_MESSAGES[self.vpn_state(name)]
        profile = self.info(name)["vpn_profile"]
        return message if profile == "none" else f"{message} (profile {profile})"

    def check_vpn_profile(self, name: str, profile: str, config: Path) -> None:
        """Refuse to treat a workspace as using a profile whose config it does not mount."""
        current = self.info(name)["vpn"]
        if current != str(config.expanduser().resolve()):
            raise RangeDockError(
                f"Workspace '{name}' does not use VPN profile '{profile}' (VPN config: {current}). "
                "Profiles apply when a workspace is created."
            )

    def vpn_connect(self, name: str) -> str:
        """Start OpenVPN and wait briefly for the tunnel to come up."""
        container, details = self._vpn_workspace(name)
        if not details.get("State", {}).get("Running"):
            self.docker.call(["container", "start", container])
            self._reset_vpn(container, details)
        else:
            self.docker.call(["container", "exec", "--user", "root", container, "rm", "-f", VPN_DISABLED])
        self._start_vpn(container, details)
        deadline = time.monotonic() + VPN_CONNECT_TIMEOUT
        while self.vpn_state(name) == "connecting" and time.monotonic() < deadline:
            time.sleep(0.5)
        return self.vpn_status(name)

    def vpn_disconnect(self, name: str) -> str:
        container, details = self._vpn_workspace(name)
        if not details.get("State", {}).get("Running"):
            return "workspace stopped"
        self.docker.call(["container", "exec", "--user", "root", container, "touch", VPN_DISABLED])
        if self._vpn_running(container):
            pid = self.docker.call(["container", "exec", "--user", "root", container, "cat", VPN_PID])
            self.docker.call(["container", "exec", "--user", "root", container,
                              "python3", "-c", "import os,sys,signal; os.kill(int(sys.argv[1]), signal.SIGTERM)", pid])
        self.docker.call(["container", "exec", "--user", "root", container, "rm", "-f", VPN_PID])
        return "OpenVPN stopped"

    def vpn_logs(self, name: str) -> str:
        container, _ = self._vpn_workspace(name)
        return self.docker.call(["container", "exec", "--user", "root", container,
                                 "tail", "-n", "40", VPN_LOG])

    def desktop_url(self, name: str) -> str:
        container, details = self._managed(name)
        if (details.get("Config", {}).get("Labels") or {}).get(PROFILE_LABEL) != "desktop":
            raise RangeDockError(
                f"Workspace '{name}' does not use the desktop image. "
                "Create a desktop workspace with 'rangedock create NAME --image desktop'."
            )
        self.start(name)
        for _ in range(50):
            try:
                self.docker.call(["container", "exec", container, "nc", "-z", "127.0.0.1", "6080"])
                break
            except RangeDockError:
                time.sleep(0.2)
        else:
            raise RangeDockError(f"Desktop did not become ready for '{name}'. Check 'docker logs {container}'.")
        _, details = self._managed(name)
        ports = (details.get("NetworkSettings", {}).get("Ports") or {}).get("6080/tcp") or []
        if not ports:
            raise RangeDockError(f"Desktop port is unavailable for '{name}'.")
        return f"http://127.0.0.1:{ports[0]['HostPort']}/vnc.html?autoconnect=1"

    def burp(self, name: str) -> str:
        url = self.desktop_url(name)
        container = container_name(name)
        try:
            self.docker.call(["container", "exec", container, "test", "-x", "/usr/bin/burpsuite"])
        except RangeDockError:
            self.docker.call(["container", "exec", "--user", "root", container,
                              "apt-get", "update"], interactive=True)
            self.docker.call(["container", "exec", "--user", "root", container,
                              "apt-get", "install", "-y", "--no-install-recommends", "burpsuite"],
                             interactive=True)
        self._launch_on_desktop(container, ["burpsuite"])
        return url

    def desktop_launch(self, name: str, command: list[str]) -> str:
        """Start a GUI program on the workspace desktop and return the desktop URL."""
        if not command:
            raise RangeDockError("Name a program to launch on the desktop, for example: xterm")
        url = self.desktop_url(name)
        self._launch_on_desktop(container_name(name), command)
        return url

    def _launch_on_desktop(self, container: str, command: list[str]) -> None:
        self.docker.call(["container", "exec", "-d", "--env", "DISPLAY=:1", container, *command])

    def enter(self, name: str) -> None:
        self.start(name)
        container = container_name(name)
        self.docker.call(["container", "exec", tty_flags(), container, "bash"], interactive=True)

    def run(self, name: str, command: list[str]) -> None:
        if not command:
            raise RangeDockError("Pass a command after --, for example: rangedock run lab -- nmap --version")
        self.start(name)
        container = container_name(name)
        self.docker.call(["container", "exec", container, *command], interactive=True)

    def execute(self, name: str, command: list[str], *, workdir: str = "/workspace") -> int:
        """Run a command attached to the terminal and return its exit code."""
        container, details = self._managed(name)
        if not details.get("State", {}).get("Running"):
            self.start(name)
        return self.docker.status(["container", "exec", tty_flags(), "--workdir", workdir, container, *command])

    def capture(self, name: str, command: list[str], *, workdir: str = "/workspace") -> str:
        """Run a non-interactive command in a running workspace and return its output."""
        container, details = self._managed(name)
        if not details.get("State", {}).get("Running"):
            self.start(name)
        return self.docker.call(["container", "exec", "--workdir", workdir, container, *command])

    def list(self) -> list[dict]:
        self.daemon()
        output = self.docker.call([
            "container", "ls", "-a", "--filter", f"label={LABEL}=true", "--format", "{{json .}}"
        ])
        return [json.loads(line) for line in output.splitlines() if line.strip()]

    def stop(self, name: str) -> bool:
        container, details = self._managed(name)
        if not details.get("State", {}).get("Running"):
            return False
        self.docker.call(["container", "stop", container])
        return True

    def remove(self, name: str) -> None:
        container, details = self._managed(name)
        if details.get("State", {}).get("Running"):
            raise RangeDockError(f"Stop '{name}' before removing it. Workspace files will remain on disk.")
        self.docker.call(["container", "rm", container])
