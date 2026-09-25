"""Human-facing command line for local workspaces."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from .completion import command_tree
from .console import last_workspace, open_console
from .core import IMAGES, PROFILES, RangeDockError, Workbench
from .preferences import SETTINGS, Preferences, format_value
from .pwn import open_pwn
from .profiles import VPN_TYPES, ProfileStore
from .tools import describe_tool, workspace_tools
from .tour import run_tour, show_tour


def workspace_options(command: argparse.ArgumentParser) -> None:
    source = command.add_mutually_exclusive_group()
    source.add_argument("--workspace", type=Path, help="host folder to mount at /workspace")
    source.add_argument("--cwd", action="store_true", help="mount the current folder at /workspace")
    command.add_argument("--image", choices=PROFILES, help="image profile (default: web)")
    vpn = command.add_mutually_exclusive_group()
    vpn.add_argument("--vpn", type=Path, help="OpenVPN .ovpn/.conf file; enables NET_ADMIN and /dev/net/tun")
    vpn.add_argument("--vpn-profile", metavar="PROFILE", help="saved VPN profile (see 'rangedock vpn profile')")


def vpn_config(args: argparse.Namespace, store: ProfileStore) -> tuple[Path | None, str | None]:
    """Return the VPN config path and profile name selected by --vpn or --vpn-profile."""
    if args.vpn_profile is None:
        return args.vpn, None
    profile = store.resolve(args.vpn_profile)
    return profile.config, profile.name


def require_profile(bench: Workbench, store: ProfileStore, name: str, profile_name: str) -> None:
    profile = store.get(profile_name)
    bench.check_vpn_profile(name, profile.name, profile.config)


def show_profiles(store: ProfileStore) -> None:
    profiles = store.list()
    if not profiles:
        print("No VPN profiles yet. Add one with 'rangedock vpn profile add NAME --config FILE'.")
    for profile in profiles:
        print(f"{profile.name:<16} {profile.type:<8} {'ready' if profile.available else 'missing':<8} {profile.config}")
    for profile in profiles:
        if not profile.available:
            print(f"rangedock: warning: VPN profile '{profile.name}' points to a missing file: {profile.config}",
                  file=sys.stderr)


def show_profile(store: ProfileStore, name: str) -> None:
    profile = store.get(name)
    print(f"{'Name':<11} {profile.name}")
    print(f"{'Type':<11} {profile.type}")
    print(f"{'Config':<11} {profile.config}")
    print(f"{'Mounted':<11} {profile.config_dir} -> /vpn (read-only)")
    print(f"{'Status':<11} {'ready' if profile.available else 'missing'}")
    if not profile.available:
        print(f"rangedock: warning: config file is missing: {profile.config}", file=sys.stderr)


def show_settings(preferences: Preferences) -> None:
    values = preferences.values()
    width = max(len(key) for key in SETTINGS)
    for key, setting in SETTINGS.items():
        print(f"{key:<{width}}  {format_value(values[key]):<7}  {setting.help}")


def show_tools(bench: Workbench, name: str, tool_name: str | None) -> None:
    catalog = workspace_tools(bench, name)
    if tool_name is not None:
        tool = catalog.find(tool_name)
        if tool is None:
            raise RangeDockError(f"'{tool_name}' is not in the tool manifest for '{name}'.")
        print("\n".join(describe_tool(tool)))
        return
    print(f"Source: {catalog.source}")
    for tool in sorted(catalog.tools, key=lambda item: (item.category, item.name)):
        print(f"{tool.name:<14} {tool.category:<12} {tool.description}")


def run_benchmark(bench: Workbench, name: str, runs: int) -> None:
    """Time repeated re-entry into a running workspace and report median and p95."""
    import statistics
    import time

    bench.start(name)
    details = bench.info(name)
    samples = []
    for _ in range(runs):
        started = time.monotonic()
        bench.capture(name, ["true"])
        samples.append((time.monotonic() - started) * 1000)
    samples.sort()
    p95 = samples[min(len(samples) - 1, int(round(0.95 * (len(samples) - 1))))]
    print(f"Workspace {name} ({details['profile']}, image {details['image_id'][:19]})")
    print(f"Re-enter (exec) over {runs} runs: "
          f"median {statistics.median(samples):.0f} ms, p95 {p95:.0f} ms, min {samples[0]:.0f} ms")
    print("Measured inside this host with the workspace already running; not a published benchmark.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rangedock", description="Named Docker workspaces for security labs."
    )
    sub = parser.add_subparsers(dest="action", required=True)
    tour = sub.add_parser("tour", help="learn the workflow or try it in a practice workspace")
    tour.add_argument("--run", action="store_true", help="create a practice workspace and run the lesson")
    tour.add_argument("--name", default="tour", help="practice workspace name (default: tour)")
    tour.add_argument("--workspace", type=Path, help="host folder for the practice workspace")
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
    vpn = sub.add_parser("vpn", help="control OpenVPN in a workspace and manage VPN profiles")
    vpn_sub = vpn.add_subparsers(dest="vpn_action", required=True)
    for action, help_text in [
        ("status", "show whether OpenVPN is running"),
        ("connect", "start OpenVPN, starting the workspace if needed"),
        ("disconnect", "stop OpenVPN until the next connect"),
        ("logs", "show the latest OpenVPN log lines"),
    ]:
        command = vpn_sub.add_parser(action, help=help_text)
        command.add_argument("name")
        if action == "connect":
            command.add_argument("--profile", dest="vpn_profile", metavar="PROFILE",
                                 help="check that the workspace uses this VPN profile")
    profile = vpn_sub.add_parser("profile", help="save, list, show, or remove named VPN profiles")
    profile_sub = profile.add_subparsers(dest="profile_action", required=True)
    add = profile_sub.add_parser("add", help="remember a VPN config by name (files are not copied)")
    add.add_argument("profile_name", metavar="NAME")
    add.add_argument("--config", type=Path, required=True, help="OpenVPN .ovpn/.conf file")
    add.add_argument("--type", dest="vpn_type", choices=VPN_TYPES, default="openvpn", help="VPN type")
    profile_sub.add_parser("list", help="show saved VPN profiles")
    for action, help_text in [
        ("show", "show one VPN profile"),
        ("remove", "forget a VPN profile; its files stay on disk"),
    ]:
        profile_sub.add_parser(action, help=help_text).add_argument("profile_name", metavar="NAME")
    console = sub.add_parser("console", help="open the interactive lab console for a workspace")
    target = console.add_mutually_exclusive_group(required=True)
    target.add_argument("name", nargs="?")
    target.add_argument("--last", action="store_true", help="reopen the most recent console workspace")
    console.add_argument("--profile", dest="vpn_profile", metavar="VPN_PROFILE",
                         help="check that the workspace uses this VPN profile and connect it")
    console.add_argument("--plain", action="store_true", help="simple line prompt without menus or colors")
    pwn = sub.add_parser("pwn", help="EXPERIMENTAL: AI-assisted CTF mode; AI proposes, you approve each command")
    pwn.add_argument("name")
    pwn.add_argument("--target", required=True, metavar="HOST", help="the host you are authorized to test")
    pwn.add_argument("--max-steps", type=int, default=40, dest="max_steps",
                     help="stop after this many executed commands (default: 40)")
    tools = sub.add_parser("tools", help="list the tools a workspace image provides")
    tools.add_argument("name")
    tools.add_argument("--tool", metavar="NAME", help="show one tool's options instead of the full list")
    bench_command = sub.add_parser("bench", help="time re-entry into a workspace on this host")
    bench_command.add_argument("name")
    bench_command.add_argument("--runs", type=int, default=20, help="number of samples (default: 20)")
    config = sub.add_parser("config", help="show or change persisted preferences")
    config_sub = config.add_subparsers(dest="config_action", required=True)
    config_sub.add_parser("list", help="show all settings and their values")
    config_get = config_sub.add_parser("get", help="show one setting")
    config_get.add_argument("key", choices=list(SETTINGS))
    config_set = config_sub.add_parser("set", help="change one setting")
    config_set.add_argument("key", choices=list(SETTINGS))
    config_set.add_argument("value")
    config_reset = config_sub.add_parser("reset", help="restore one setting to its default")
    config_reset.add_argument("key", choices=list(SETTINGS))
    return parser


def open_browser(no_browser: bool, preferences: Preferences) -> bool:
    return not no_browser and preferences.get("desktop.open_browser")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bench = Workbench()
    store = ProfileStore()
    preferences = Preferences()
    try:
        if args.action == "tour":
            if args.run:
                run_tour(bench, args.name, args.workspace)
            else:
                if args.workspace is not None:
                    raise RangeDockError("--workspace is only used with 'rangedock tour --run'.")
                show_tour(args.name)
        elif args.action == "doctor":
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
            vpn, vpn_profile = vpn_config(args, store)
            bench.open(args.name, Path.cwd() if args.cwd else args.workspace,
                       profile=args.image, vpn=vpn, vpn_profile=vpn_profile)
        elif args.action == "create":
            vpn, vpn_profile = vpn_config(args, store)
            folder = bench.create(args.name, Path.cwd() if args.cwd else args.workspace,
                                  profile=args.image or "web", vpn=vpn, vpn_profile=vpn_profile)
            print(f"Created {args.name} -> {folder}")
            if vpn_profile:
                print(f"VPN profile: {vpn_profile}")
            print(f"Enter with: rangedock enter {args.name}")
        elif args.action == "enter":
            bench.enter(args.name)
        elif args.action == "start":
            print(f"{'Started' if bench.start(args.name) else 'Already running'} {args.name}")
        elif args.action == "restart":
            print(f"{bench.restart(args.name)} {args.name}")
        elif args.action == "info":
            details = bench.info(args.name)
            for label, key in [("Name", "name"), ("Status", "status"), ("Image", "image"),
                               ("Profile", "profile"), ("Workspace", "workspace"), ("VPN", "vpn"),
                               ("VPN profile", "vpn_profile"), ("Created", "created")]:
                print(f"{label:<12} {details[key]}")
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
            if open_browser(args.no_browser, preferences):
                webbrowser.open(url)
        elif args.action == "burp":
            url = bench.burp(args.name)
            print(f"Burp desktop: {url}")
            if open_browser(args.no_browser, preferences):
                webbrowser.open(url)
        elif args.action == "vpn":
            if args.vpn_action == "profile":
                if args.profile_action == "add":
                    profile = store.add(args.profile_name, args.config, args.vpn_type)
                    print(f"Saved VPN profile '{profile.name}'.")
                elif args.profile_action == "list":
                    show_profiles(store)
                elif args.profile_action == "show":
                    show_profile(store, args.profile_name)
                elif args.profile_action == "remove":
                    profile = store.remove(args.profile_name)
                    print(f"Removed VPN profile '{profile.name}'. Files were not changed: {profile.config_dir}")
            elif args.vpn_action == "status":
                print(bench.vpn_status(args.name))
            elif args.vpn_action == "connect":
                if args.vpn_profile:
                    require_profile(bench, store, args.name, args.vpn_profile)
                print(bench.vpn_connect(args.name))
            elif args.vpn_action == "disconnect":
                print(bench.vpn_disconnect(args.name))
            elif args.vpn_action == "logs":
                print(bench.vpn_logs(args.name))
        elif args.action == "console":
            name = last_workspace() if args.last else args.name
            bench.info(name)
            if args.vpn_profile:
                require_profile(bench, store, name, args.vpn_profile)
                print(bench.vpn_connect(name))
            open_console(bench, name, tree=command_tree(build_parser()), dispatch=main,
                         plain=args.plain, preferences=preferences)
        elif args.action == "pwn":
            bench.info(args.name)
            return open_pwn(bench, args.name, target=args.target, max_steps=args.max_steps)
        elif args.action == "tools":
            show_tools(bench, args.name, args.tool)
        elif args.action == "bench":
            run_benchmark(bench, args.name, args.runs)
        elif args.action == "config":
            if args.config_action == "list":
                show_settings(preferences)
            elif args.config_action == "get":
                print(format_value(preferences.get(args.key)))
            elif args.config_action == "set":
                print(f"{args.key} = {format_value(preferences.set(args.key, args.value))}")
            elif args.config_action == "reset":
                print(f"{args.key} = {format_value(preferences.reset(args.key))} (default)")
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
