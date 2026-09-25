# RangeDock

**A named Docker workspace for every security lab.** Build one small tools image, open a workspace, leave it, and come back to the same files. RangeDock keeps the Docker commands short and keeps workspaces separate.

See the [roadmap](ROADMAP.md) for the path to a dependable free workstation and possible team services.

RangeDock is an independent project. It contains original code and a Kali-based image; it does not use Exegol code, images, or assets.

## What it does

```text
your terminal                      Docker container
rangedock open lab ──────────────> rangedock-lab + bash
  host folder ~/rangedock-workspaces/lab ↔ /workspace
rangedock open lab ──────────────> re-enter the same workspace
rangedock stop lab ──────────────> container stops; files stay
```

The bundled image includes general lab tools (`nmap`, `curl`, `dig`, `whois`, `netcat`, `git`, `jq`, Python, `ripgrep`, and `tmux`), password tools (`john`, `hydra`), web tools (`sqlmap`, `ffuf`, `gobuster`, `nikto`, `dirb`, `whatweb`, `wfuzz`, `feroxbuster`), and network helpers (`dnsrecon`, `tcpdump`, `socat`, `proxychains4`). It runs as an unprivileged user. Containers are created without privileged mode or host networking. Some network capture operations require Docker capabilities that RangeDock does not currently grant.

Wordlists are available at `/usr/share/wordlists/` and `/usr/share/seclists/`. Kali's `rockyou.txt.gz` stays compressed; extract it into your workspace when needed: `gzip -dc /usr/share/wordlists/rockyou.txt.gz > /workspace/rockyou.txt`. SecLists adds roughly 1.8 GB of installed content. The v0.2.1 image measured 4.25 GB locally on the maintainer's Docker Desktop, so the first build needs several GB of free disk space and can take a while. This is a curated toolkit, not every Kali package.
On Linux and macOS, RangeDock uses your host user ID inside the container so files written to the mounted workspace stay yours.

## Install

Requires Python 3.10+ and Docker Engine or Docker Desktop running Linux containers. On Windows, start Docker Desktop and switch to Linux containers before using RangeDock. On macOS, use Docker Desktop or another Docker-compatible Linux engine.

If using Lima directly on macOS, its host home mount is [read-only by default](https://lima-vm.io/docs/usage/). Start Lima with `--mount-writable` so files in `/workspace` can be written from the container.

```bash
pipx install git+https://github.com/shookapic/rangedock.git
rangedock doctor
rangedock build
```

You can use `uv tool install git+https://github.com/shookapic/rangedock.git` or `python -m pip install git+https://github.com/shookapic/rangedock.git` instead of pipx. The image is built locally from the [bundled Dockerfile](src/rangedock/Dockerfile). The first build downloads Kali packages, so it needs a network connection; later container operations use the local image.

If you do not have pipx or uv, see their [pipx installation](https://pipx.pypa.io/latest/how-to/install-pipx.html) or [uv installation](https://docs.astral.sh/uv/getting-started/installation/) instructions. If `rangedock` is not found after installation, open a new terminal and check that your tool install directory is on `PATH`.

Upgrading from v0.2.0: existing containers remain usable. Run `rangedock build` after upgrading to create the v0.2.1 image. New workspaces use it. To put an existing workspace on the new image, run `rangedock stop NAME`, `rangedock remove NAME`, then `rangedock open NAME` with the same `--workspace` option if you used a custom folder. The host workspace files remain in place.

## First workspace

```bash
rangedock open lab
```

Try the added tools in a workspace with `john --list=build-info`, `hydra -U http-get`, or `ls /usr/share/seclists/Discovery/Web-Content`. From the host, use `rangedock run lab -- john --list=build-info`.

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

## Scope of version 0.2.1

This release manages local, named workspaces and one bundled image. Burp Suite is not bundled because RangeDock has no graphical desktop yet; installing the GUI package alone would not make it usable through `rangedock open`. The release does not include VPN management, privileged hardware access, or prebuilt image downloads. It does not scan any target on its own. Use network tools only on systems you own or have permission to assess.

The Docker daemon has broad access to its host. RangeDock checks its management label before stopping or removing a container, but that label is an ownership guard, not a security boundary. Inspect the Dockerfile before building and mount only folders you intend to share.

## macOS smoke check

The macOS CI job checks the Python CLI; a Docker lifecycle check on a Mac is still manual. After `rangedock build`, run `rangedock open mac-smoke`, then inside the shell:

```bash
echo working > /workspace/proof.txt
exit
```

On the host, run `cat ~/rangedock-workspaces/mac-smoke/proof.txt`. It should print `working`. Then run `rangedock stop mac-smoke` and `rangedock remove mac-smoke`. The host folder and file stay in place.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
docker build -t rangedock:test src/rangedock
```

The RangeDock CLI is MIT licensed. The Kali base, installed tools, and wordlists retain their own licenses. Issues and contributions welcome.
