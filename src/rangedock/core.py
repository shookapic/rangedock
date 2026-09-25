"""Docker lifecycle with explicit ownership and no shell interpolation."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from importlib import resources
from pathlib import Path

IMAGE = "rangedock:0.2.1"
LABEL = "dev.rangedock.managed"
WORKSPACE_LABEL = "dev.rangedock.workspace"
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


def valid_name(name: str) -> str:
    if not NAME_RE.fullmatch(name):
        raise RangeDockError("Name must start with a lowercase letter and contain only a-z, 0-9, or - (max 40).")
    return name


def container_name(name: str) -> str:
    return f"rangedock-{valid_name(name)}"


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

    def image_exists(self) -> bool:
        try:
            self.docker.call(["image", "inspect", IMAGE, "--format", "{{.Id}}"])
            return True
        except RangeDockError:
            return False

    def build(self) -> None:
        self.linux_daemon()
        dockerfile = resources.files("rangedock").joinpath("Dockerfile").read_text(encoding="utf-8")
        self.docker.call(["build", "--pull", "-t", IMAGE, "-"], input_text=dockerfile,
                         interactive=True)

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

    def create(self, name: str, workspace: Path | None = None) -> Path:
        container = container_name(name)
        self.linux_daemon()
        if self.container_exists(name):
            raise RangeDockError(f"Container '{container}' already exists. Use 'rangedock open {name}' or another name.")
        if not self.image_exists():
            raise RangeDockError(f"Image {IMAGE} is missing. Run 'rangedock build' first.")
        folder = (workspace or Path.home() / "rangedock-workspaces" / name).expanduser().resolve()
        if "," in str(folder):
            raise RangeDockError("Workspace path cannot contain a comma (Docker mount syntax).")
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RangeDockError(f"Cannot create workspace folder {folder}: {exc}") from exc
        if not folder.is_dir():
            raise RangeDockError(f"Workspace path is not a directory: {folder}")
        self.docker.call([
            "container", "create", "--name", container,
            "--label", f"{LABEL}=true",
            "--label", f"{WORKSPACE_LABEL}={folder}",
            "--init", "--security-opt", "no-new-privileges",
            "--mount", f"type=bind,source={folder},target=/workspace",
            "--workdir", "/workspace", *host_user_options(), IMAGE,
        ])
        return folder

    def open(self, name: str, workspace: Path | None = None) -> None:
        if self.container_exists(name):
            existing = self.info(name)
            if workspace is not None and workspace.expanduser().resolve() != Path(existing["workspace"]):
                raise RangeDockError(
                    f"Workspace '{name}' already uses {existing['workspace']}. Choose another name or omit --workspace."
                )
        else:
            self.create(name, workspace)
        self.enter(name)

    def info(self, name: str) -> dict[str, str]:
        _, details = self._managed(name)
        labels = details.get("Config", {}).get("Labels") or {}
        state = details.get("State", {})
        return {
            "name": name,
            "status": state.get("Status") or ("running" if state.get("Running") else "stopped"),
            "image": details.get("Config", {}).get("Image", "unknown"),
            "workspace": labels.get(WORKSPACE_LABEL, "unknown"),
            "created": details.get("Created", "unknown"),
        }

    def start(self, name: str) -> bool:
        container, details = self._managed(name)
        if details.get("State", {}).get("Running"):
            return False
        self.docker.call(["container", "start", container])
        return True

    def restart(self, name: str) -> str:
        container, details = self._managed(name)
        if details.get("State", {}).get("Running"):
            self.docker.call(["container", "restart", container])
            return "Restarted"
        self.docker.call(["container", "start", container])
        return "Started"

    def enter(self, name: str) -> None:
        self.start(name)
        container = container_name(name)
        flags = "-it" if sys.stdin.isatty() and sys.stdout.isatty() else "-i"
        self.docker.call(["container", "exec", flags, container, "bash"], interactive=True)

    def run(self, name: str, command: list[str]) -> None:
        if not command:
            raise RangeDockError("Pass a command after --, for example: rangedock run lab -- nmap --version")
        self.start(name)
        container = container_name(name)
        self.docker.call(["container", "exec", container, *command], interactive=True)

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
