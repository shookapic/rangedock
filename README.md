# RangeDock

**A named Docker workspace for every security lab.** Pull a ready image, open a workspace, leave it, and come back to the same files. RangeDock keeps the Docker commands short and keeps workspaces separate.

See the [roadmap](ROADMAP.md) for the path to a dependable free workstation and possible team services.
New to RangeDock? Start with the [guided tutorial](TUTORIAL.md), or run `rangedock tour` after installing the CLI.

RangeDock is an independent project. It contains original code and Kali-based images; it does not use Exegol code, images, or assets.

## What it does

```text
your terminal                      Docker container
rangedock open lab ──────────────> rangedock-lab + bash
  host folder ~/rangedock-workspaces/lab ↔ /workspace
rangedock open lab ──────────────> re-enter the same workspace
rangedock stop lab ──────────────> container stops; files stay
```

Choose an image when creating a workspace:

| Image | Contents | Local size measured on Docker Desktop |
| --- | --- | ---: |
| `base` | Shell, Nmap, OpenVPN, and general lab tools | 566 MB |
| `web` (default) | Base plus John, Hydra, SQLMap, web tools, Kali wordlists, and SecLists | 4.26 GB |
| `desktop` | Web plus a browser desktop (noVNC, Xvfb, Openbox) | 4.92 GB |

All images run as an unprivileged user. Containers are created without privileged mode or host networking. Nmap runs without raw-socket privileges, so use TCP connect scans (`-sT`). Packet capture and raw-socket scans require capabilities that default workspaces do not grant.

The `web` and `desktop` images include wordlists at `/usr/share/wordlists/` and `/usr/share/seclists/`. Kali's `rockyou.txt.gz` stays compressed; extract it into your workspace when needed: `gzip -dc /usr/share/wordlists/rockyou.txt.gz > /workspace/rockyou.txt`. SecLists adds roughly 1.8 GB of installed content. These are curated images, not every Kali package.
On Linux and macOS, RangeDock uses your host user ID inside the container so files written to the mounted workspace stay yours.

## Install

Requires Python 3.10+ and Docker Engine or Docker Desktop running Linux containers. On Windows, start Docker Desktop and switch to Linux containers before using RangeDock. On macOS, use Docker Desktop or another Docker-compatible Linux engine.

If using Lima directly on macOS, its host home mount is [read-only by default](https://lima-vm.io/docs/usage/). Start Lima with `--mount-writable` so files in `/workspace` can be written from the container.

```bash
pipx install git+https://github.com/shookapic/rangedock.git
rangedock doctor
rangedock open lab
```

You can use `uv tool install git+https://github.com/shookapic/rangedock.git` or `python -m pip install git+https://github.com/shookapic/rangedock.git` instead of pipx. On first use, RangeDock pulls the versioned `web` image from GitHub Container Registry. Later container operations use the local image. You can pull another image with `rangedock image pull base` or build from the [bundled Dockerfile](src/rangedock/Dockerfile) with `rangedock build base`, `rangedock build web`, or `rangedock build desktop`.

If you do not have pipx or uv, see their [pipx installation](https://pipx.pypa.io/latest/how-to/install-pipx.html) or [uv installation](https://docs.astral.sh/uv/getting-started/installation/) instructions. If `rangedock` is not found after installation, open a new terminal and check that your tool install directory is on `PATH`.

Upgrading from v0.2.x: existing containers remain usable on their original image. New workspaces use v0.3 images. To move an existing workspace to the new image, note its folder with `rangedock info NAME`, then run `rangedock stop NAME`, `rangedock remove NAME`, and `rangedock open NAME --workspace PATH`. Files in the mounted host folder remain; changes stored only inside the old container do not. `rangedock image update web` refreshes the local image tag but never changes existing containers.

## First workspace

Run `rangedock tour` for a read-only command walkthrough. Run `rangedock tour --run` to try it with a small `base` workspace. The hands-on tour creates `~/rangedock-workspaces/tour/rangedock-tour.txt`, demonstrates that the file survives a container restart, and leaves the practice container stopped. `rangedock remove tour` removes that container while keeping the host files. Use `--name` or `--workspace` to choose another practice location. The base image may download on first use.
The v0.3.1 CLI uses the tested v0.3.0 images; tutorial changes do not require downloading new images.

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

`rangedock doctor` checks Docker and shows which local images are ready. `rangedock image list` shows the same image catalog. If a pull fails, check GHCR access or run `rangedock build web` locally.

## Browser desktop and Burp

```bash
rangedock create gui-lab --image desktop
rangedock desktop gui-lab
rangedock burp gui-lab
```

The desktop opens in your browser through a port bound to `127.0.0.1`. It has no VNC password, so do not forward that port to other machines. `rangedock burp` installs Burp from Kali inside **your own running container**, launches it, and opens the desktop. The public desktop image does not contain Burp because [PortSwigger's Community Edition terms](https://portswigger.net/burp/eula) do not grant redistribution rights. Accept its terms in the GUI when prompted. The installation stays in that container across restarts, but removing the container removes it.

## OpenVPN workspaces

```bash
rangedock create vpn-lab --vpn /path/to/client.ovpn
rangedock vpn connect vpn-lab
rangedock vpn status vpn-lab
rangedock vpn logs vpn-lab
rangedock vpn disconnect vpn-lab
```

RangeDock mounts the config directory read-only at `/vpn`, so put referenced credential and certificate files in that directory and use relative paths in the config. VPN workspaces receive only `NET_ADMIN` and `/dev/net/tun`; other workspaces do not. OpenVPN reconnects when a configured workspace is restarted through RangeDock. `vpn status` reports whether the process is running; inspect `vpn logs` to confirm tunnel negotiation. Device support depends on the Docker host. WireGuard is not yet supported.

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

## Scope of version 0.3

This release manages local named workspaces, versioned images, an opt-in browser desktop, and OpenVPN process control. It does not provide WireGuard, a VPN server, or host-wide VPN routing. It does not scan any target on its own. Use network tools only on systems you own or have permission to assess.

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
docker build --target web -t rangedock:test src/rangedock
```

The RangeDock CLI is MIT licensed. The Kali base, installed tools, and wordlists retain their own licenses. Issues and contributions welcome.
