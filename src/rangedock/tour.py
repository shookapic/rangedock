"""A small first-run lesson using the same workspace operations as the CLI."""

from __future__ import annotations

from pathlib import Path

from .core import RangeDockError, Workbench, valid_name


def show_tour(name: str) -> None:
    valid_name(name)
    print("RangeDock tour: a workspace is a named Docker container plus a host folder.\n")
    print("1. Check Docker and see the available image profiles:")
    print("   rangedock doctor")
    print("   rangedock image list\n")
    print("2. Create a small practice workspace, then run a tool inside it:")
    print(f"   rangedock create {name} --image base")
    print(f"   rangedock run {name} -- nmap --version\n")
    print("3. Open a shell, leave it with 'exit', and come back later:")
    print(f"   rangedock enter {name}")
    print(f"   rangedock info {name}")
    print(f"   rangedock stop {name}")
    print(f"   rangedock open {name}\n")
    print("Files in /workspace live in the host folder shown by 'rangedock info'.")
    print("Removing a stopped container keeps those files:")
    print(f"   rangedock stop {name}")
    print(f"   rangedock remove {name}\n")
    print("Optional: 'rangedock create gui-lab --image desktop' followed by")
    print("'rangedock desktop gui-lab' opens a browser desktop. 'rangedock burp gui-lab'")
    print("installs and opens Burp in that workspace. Add --vpn FILE when creating a")
    print("workspace to use an OpenVPN configuration.\n")
    print(f"Run 'rangedock tour --run --name {name}' to try the base steps automatically.")


def run_tour(bench: Workbench, name: str, workspace: Path | None = None) -> Path:
    valid_name(name)
    folder = (workspace or Path.home() / "rangedock-workspaces" / name).expanduser().resolve()
    try:
        if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
            raise RangeDockError(f"Tour folder {folder} is not empty. Choose another --name or --workspace.")
    except OSError as exc:
        raise RangeDockError(f"Cannot inspect tour folder {folder}: {exc}") from exc
    if bench.container_exists(name):
        raise RangeDockError(f"Workspace '{name}' already exists. Choose another --name.")

    def announce(message: str) -> None:
        print(message, flush=True)

    announce("Checking Docker and creating a base workspace. The image may download on first use.")
    announce(f"  rangedock create {name} --image base")
    folder = bench.create(name, folder, profile="base")
    announce(f"Workspace: {folder} (mounted at /workspace in the container)\n")

    announce("Running a tool inside the workspace:")
    announce(f"  rangedock run {name} -- nmap --version")
    bench.run(name, ["nmap", "--version"])

    note = folder / "rangedock-tour.txt"
    try:
        note.write_text("This file stays on your host when the workspace stops.\n", encoding="utf-8")
    except OSError as exc:
        raise RangeDockError(f"Could not write the tour file in {folder}: {exc}") from exc
    announce("\nReading a host file through the /workspace mount:")
    bench.run(name, ["cat", "/workspace/rangedock-tour.txt"])

    announce("\nStopping and reopening the workspace to check that the file persists:")
    bench.stop(name)
    bench.run(name, ["cat", "/workspace/rangedock-tour.txt"])
    bench.stop(name)

    announce(f"\nTour complete. '{name}' is stopped; its host files remain in {folder}.")
    announce(f"Explore with: rangedock enter {name}")
    announce(f"Remove the container with: rangedock remove {name}")
    announce("The remove command keeps the host folder and its files.")
    return folder
