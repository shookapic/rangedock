"""Human-facing command line for local workspaces."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from .core import IMAGES, PROFILES, RangeDockError, Workbench


def workspace_options(command: argparse.ArgumentParser) -> None:
    source = command.add_mutually_exclusive_group()
    source.add_argument("--workspace", type=Path, help="host folder to mount at /workspace")
    source.add_argument("--cwd", action="store_true", help="mount the current folder at /workspace")
    command.add_argument("--image", choices=PROFILES, help="image profile (default: web)")
    command.add_argument("--vpn", type=Path, help="OpenVPN .ovpn/.conf file; enables NET_ADMIN and /dev/net/tun")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rangedock", description="Named Docker workspaces for security labs."
    )
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("doctor", help="check Docker and local images")
    build = sub.add_parser("build", help="build an image locally")
    build.add_argument("profile", choices=PROFILES, nargs="?", default="web")
    image = sub.add_parser("image", help="list, pull, or update versioned images")
    image_sub = image.add_subparsers(dest="image_action", required=True)
    image_sub.add_parser("list", help="show local images")
    for action in ("pull", "update"):
        command = image_sub.add_parser(action, help=f"{action} a published image")
        command.add_argument("profile", choices=PROFILES, nargs="?", default="web")
    open_command = sub.add_parser("open", help="create if needed, then enter a workspace")
    open_command.add_argument("name")
    workspace_options(open_command)
    create = sub.add_parser("create", help="create a named persistent workspace")
    create.add_argument("name")
    workspace_options(create)
    for action, help_text in [
        ("enter", "open a shell, starting the workspace if needed"),
        ("start", "start a workspace without entering it"),
        ("restart", "restart a running workspace, or start a stopped one"),
        ("info", "show workspace status, image, and host folder"),
        ("stop", "stop a workspace"),
        ("remove", "remove a stopped container; keep its files"),
    ]:
        command = sub.add_parser(action, help=help_text)
        command.add_argument("name")
    run = sub.add_parser("run", help="run a command inside a workspace")
    run.add_argument("name")
    run.add_argument("command", nargs=argparse.REMAINDER)
    sub.add_parser("list", help="show managed workspaces")
    desktop = sub.add_parser("desktop", help="open a desktop workspace in your browser")
    desktop.add_argument("name")
    desktop.add_argument("--no-browser", action="store_true", help="only print the localhost URL")
    burp = sub.add_parser("burp", help="install Burp into your desktop workspace and launch it")
    burp.add_argument("name")
    burp.add_argument("--no-browser", action="store_true", help="only print the localhost URL")
    vpn = sub.add_parser("vpn", help="control OpenVPN in a workspace")
    vpn_sub = vpn.add_subparsers(dest="vpn_action", required=True)
    for action in ("status", "connect", "disconnect", "logs"):
        vpn_sub.add_parser(action).add_argument("name")
    args = parser.parse_args(argv)
    bench = Workbench()
    try:
        if args.action == "doctor":
            version = bench.linux_daemon()
            print(f"Docker daemon: {version} (Linux containers)")
            for profile in PROFILES:
                print(f"Local image: {IMAGES[profile]} {'ready' if bench.image_exists(profile) else 'missing (pull or build)'}")
        elif args.action == "build":
            bench.build(args.profile)
            print(f"Built {IMAGES[args.profile]}")
        elif args.action == "image":
            if args.image_action == "list":
                bench.linux_daemon()
                for profile in PROFILES:
                    print(f"{profile:<9} {IMAGES[profile]:<27} {'ready' if bench.image_exists(profile) else 'missing'}")
            else:
                bench.pull(args.profile)
                print(f"Updated {IMAGES[args.profile]}")
        elif args.action == "open":
            bench.open(args.name, Path.cwd() if args.cwd else args.workspace,
                       profile=args.image, vpn=args.vpn)
        elif args.action == "create":
            folder = bench.create(args.name, Path.cwd() if args.cwd else args.workspace,
                                  profile=args.image or "web", vpn=args.vpn)
            print(f"Created {args.name} -> {folder}")
            print(f"Enter with: rangedock enter {args.name}")
        elif args.action == "enter":
            bench.enter(args.name)
        elif args.action == "start":
            print(f"{'Started' if bench.start(args.name) else 'Already running'} {args.name}")
        elif args.action == "restart":
            print(f"{bench.restart(args.name)} {args.name}")
        elif args.action == "info":
            details = bench.info(args.name)
            for key in ("name", "status", "image", "profile", "workspace", "vpn", "created"):
                print(f"{key.capitalize():<10} {details[key]}")
        elif args.action == "run":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            bench.run(args.name, command)
        elif args.action == "list":
            rows = bench.list()
            if not rows:
                print("No workspaces yet. Run 'rangedock open NAME'.")
            for row in rows:
                print(f"{row.get('Names', '?'):<28} {row.get('Status', '?'):<22} {row.get('Image', '?')}")
        elif args.action == "desktop":
            url = bench.desktop_url(args.name)
            print(f"Desktop: {url}")
            if not args.no_browser:
                webbrowser.open(url)
        elif args.action == "burp":
            url = bench.burp(args.name)
            print(f"Burp desktop: {url}")
            if not args.no_browser:
                webbrowser.open(url)
        elif args.action == "vpn":
            if args.vpn_action == "status":
                print(bench.vpn_status(args.name))
            elif args.vpn_action == "connect":
                print(bench.vpn_connect(args.name))
            elif args.vpn_action == "disconnect":
                print(bench.vpn_disconnect(args.name))
            elif args.vpn_action == "logs":
                print(bench.vpn_logs(args.name))
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
