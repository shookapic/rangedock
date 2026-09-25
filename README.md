# RangeDock

**A named Docker workspace for every security lab.** Build one small tools image, open a workspace, leave it, and come back to the same files. RangeDock keeps the Docker commands short and keeps workspaces separate.

See the [roadmap](ROADMAP.md) for the path from this first release to a dependable free workstation and possible team services.

RangeDock is an independent project. It contains original code and a Debian-based image; it does not use Exegol code, images, or assets.

## What it does

```text
your terminal                      Docker container
rangedock open lab ──────────────> rangedock-lab + bash
  host folder ~/rangedock-workspaces/lab ↔ /workspace
rangedock open lab ──────────────> re-enter the same workspace
rangedock stop lab ──────────────> container stops; files stay
```

The bundled image includes a compact set of general lab tools: `nmap`, `curl`, `dig`, `whois`, `netcat`, `git`, `jq`, Python, `ripgrep`, and `tmux`. It runs as an unprivileged user. Containers are created without privileged mode or host networking.
On Linux and macOS, RangeDock uses your host user ID inside the container so files written to the mounted workspace stay yours.

## Install

Requires Python 3.10+ and Docker Engine or Docker Desktop running Linux containers. On Windows, start Docker Desktop and switch to Linux containers before using RangeDock. On macOS, use Docker Desktop or another Docker-compatible Linux engine.

```bash
pipx install git+https://github.com/shookapic/rangedock.git
rangedock doctor
rangedock build
```

You can use `uv tool install git+https://github.com/shookapic/rangedock.git` or `python -m pip install git+https://github.com/shookapic/rangedock.git` instead of pipx. The image is built locally from the [bundled Dockerfile](src/rangedock/Dockerfile). The first build downloads Debian packages, so it needs a network connection; later container operations use the local image.

If you do not have pipx or uv, see their [pipx installation](https://pipx.pypa.io/latest/how-to/install-pipx.html) or [uv installation](https://docs.astral.sh/uv/getting-started/installation/) instructions. If `rangedock` is not found after installation, open a new terminal and check that your tool install directory is on `PATH`.

Upgrading from v0.1: existing containers remain usable. Run `rangedock build` after upgrading to create the v0.2 image for new workspaces. Existing containers keep the image they were created with.

## First workspace

```bash
rangedock open lab
```

Inside the container, `/workspace` is a folder on your host. Exit the shell with `exit`; the container keeps running. Run `rangedock open lab` again to re-enter it. You can mount an existing host folder or the current folder:

```bash
rangedock open client-a --workspace ./client-a
rangedock open local-project --cwd
```

An existing workspace keeps its original host folder. If you pass a different `--workspace` or `--cwd` when opening it again, RangeDock reports the mismatch instead of changing its mount.

`rangedock doctor` checks that Docker is reachable, running Linux containers, and has the local image. If the daemon is unavailable, start Docker Desktop or Docker Engine. If the image is missing, run `rangedock build`.

Other commands:

```bash
rangedock list
rangedock info lab
rangedock start lab
rangedock restart lab
rangedock run lab -- nmap --version
rangedock stop lab
rangedock remove lab
```

`create` and `enter` remain available separately. `run` starts a stopped workspace automatically. `remove` only deletes a stopped RangeDock container. It does **not** delete the workspace folder or its files.

## Scope of version 0.2

This release manages local, named workspaces and one bundled image. It does not include a graphical desktop, VPN management, privileged hardware access, or prebuilt image downloads. It does not scan any target on its own. Use network tools only on systems you own or have permission to assess.

The Docker daemon has broad access to its host. RangeDock checks its management label before stopping or removing a container, but that label is an ownership guard, not a security boundary. Inspect the Dockerfile before building and mount only folders you intend to share.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
docker build -t rangedock:test src/rangedock
```

MIT licensed. Issues and contributions welcome.
