"""Human-facing command line for local workspaces."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import IMAGE, RangeDockError, Workbench


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rangedock", description="Named Docker workspaces for security labs."
    )
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("doctor", help="check Docker and the local image")
    sub.add_parser("build", help="build the bundled tools image locally")
    create = sub.add_parser("create", help="create a named persistent workspace")
    create.add_argument("name")
    create.add_argument("--workspace", type=Path, help="host folder to mount at /workspace")
    for action, help_text in [
        ("enter", "open a shell, starting the workspace if needed"),
        ("start", "start a workspace without entering it"),
        ("stop", "stop a workspace"),
        ("remove", "remove a stopped container; keep its files"),
    ]:
        command = sub.add_parser(action, help=help_text)
        command.add_argument("name")
    run = sub.add_parser("run", help="run a command inside a workspace")
    run.add_argument("name")
    run.add_argument("command", nargs=argparse.REMAINDER)
    sub.add_parser("list", help="show managed workspaces")
    args = parser.parse_args(argv)
    bench = Workbench()
    try:
        if args.action == "doctor":
            version = bench.daemon()
            print(f"Docker daemon: {version}")
            print(f"Local image: {IMAGE} {'ready' if bench.image_exists() else 'missing (run rangedock build)'}")
        elif args.action == "build":
            bench.build()
            print(f"Built {IMAGE}")
        elif args.action == "create":
            folder = bench.create(args.name, args.workspace)
            print(f"Created {args.name} -> {folder}")
            print(f"Enter with: rangedock enter {args.name}")
        elif args.action == "enter":
            bench.enter(args.name)
        elif args.action == "start":
            print(f"{'Started' if bench.start(args.name) else 'Already running'} {args.name}")
        elif args.action == "run":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            bench.run(args.name, command)
        elif args.action == "list":
            rows = bench.list()
            if not rows:
                print("No workspaces yet. Run 'rangedock create NAME'.")
            for row in rows:
                print(f"{row.get('Names', '?'):<28} {row.get('Status', '?'):<22} {row.get('Image', '?')}")
        elif args.action == "stop":
            print(f"{'Stopped' if bench.stop(args.name) else 'Already stopped'} {args.name}")
        elif args.action == "remove":
            bench.remove(args.name)
            print(f"Removed container for {args.name}. Workspace files remain on disk.")
    except RangeDockError as exc:
        print(f"rangedock: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
