# RangeDock

**A named Docker workspace for every security lab.** Build one small tools image, create a workspace, enter it, leave it, and come back to the same files. RangeDock keeps the Docker commands short and keeps workspaces separate.

RangeDock is an independent project. It contains original code and a Debian-based image; it does not use Exegol code, images, or assets.

## What it does

```text
your terminal                      Docker container
rangedock create lab ────────────> rangedock-lab
  host folder ~/rangedock-workspaces/lab ↔ /workspace
rangedock enter lab ─────────────> bash + tools
rangedock stop lab ──────────────> container stops; files stay
```

The bundled image includes a compact set of general lab tools: `nmap`, `curl`, `dig`, `whois`, `netcat`, `git`, `jq`, Python, `ripgrep`, and `tmux`. It runs as an unprivileged user. Containers are created without privileged mode or host networking.

## Install

Requires Python 3.10+ and Docker Engine or Docker Desktop running Linux containers. On Windows, start Docker Desktop before using RangeDock.

```bash
pip install git+https://github.com/shookapic/rangedock.git
rangedock doctor
rangedock build
```

The image is built locally from the [bundled Dockerfile](src/rangedock/Dockerfile). The first build downloads Debian packages, so it needs a network connection; later container operations use the local image.

## First workspace

```bash
rangedock create lab
rangedock enter lab
```

Inside the container, `/workspace` is a folder on your host. Exit the shell with `exit`; the container keeps running so you can enter again. You can choose an existing host folder instead:

```bash
rangedock create client-a --workspace ./client-a
```

Other commands:

```bash
rangedock list
rangedock start lab
rangedock run lab -- nmap --version
rangedock stop lab
rangedock remove lab
```

`run` starts a stopped workspace automatically. `remove` only deletes a stopped RangeDock container. It does **not** delete the workspace folder or its files.

## Scope of version 0.1

This first release manages local, named workspaces and one bundled image. It does not include a graphical desktop, VPN management, privileged hardware access, or prebuilt image downloads. It does not scan any target on its own. Use network tools only on systems you own or have permission to assess.

The Docker daemon has broad access to its host. RangeDock checks its management label before stopping or removing a container, but that label is an ownership guard, not a security boundary. Inspect the Dockerfile before building and mount only folders you intend to share.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
docker build -t rangedock:test src/rangedock
```

MIT licensed. Issues and contributions welcome.
