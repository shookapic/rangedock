# Your first RangeDock workspace

This walkthrough takes about five minutes once Docker is running. A RangeDock workspace is a named container with a folder from your computer mounted at `/workspace`. Files in that folder remain available after the container stops or is removed.

## 1. Check the setup

```bash
rangedock doctor
rangedock image list
```

`doctor` checks that Docker is running Linux containers. `image list` shows the three profiles: `base` for a small shell and core tools, `web` for a larger security toolkit and wordlists, and `desktop` for browser-based GUI tools. A missing image is pulled when you first create a workspace using it.

## 2. Try the guided tour

```bash
rangedock tour
rangedock tour --run
```

The first command only explains the workflow. `--run` creates a practice workspace named `tour` using the `base` image, runs Nmap's version command, writes `rangedock-tour.txt` to its host folder, reads it through the container, then stops and restarts the container to demonstrate persistence. It leaves the container stopped. The base image may download on first use.

The practice files live in `~/rangedock-workspaces/tour` (on Windows, under your user profile). If you already use `tour`, choose a fresh name with `rangedock tour --run --name my-tour`. To put the practice files elsewhere, add `--workspace PATH`; that folder must be empty.

## 3. Explore and clean up

```bash
rangedock info tour
rangedock enter tour
```

Inside the shell, try `pwd`, `ls /workspace`, and `nmap --version`. Type `exit` to leave. You can re-enter the same workspace later.

For a guided prompt instead of plain Bash, run `rangedock console tour`. Type `nm` and press `Tab` to complete `nmap`, press `Ctrl-K` for the command palette, and `Ctrl-D` to leave.

```bash
rangedock stop tour
rangedock remove tour
```

`remove` deletes the stopped container. It leaves the host folder and `rangedock-tour.txt` in place so you can keep the file or delete it yourself.

## 4. Make a workspace for real work

```bash
rangedock open lab
```

This creates a `web` workspace if `lab` does not exist, then opens its shell. The first launch may pull a large image. Later `rangedock open lab` reuses the same container and folder. Use `rangedock info lab` to see its host path.

For a browser desktop, use a different workspace:

```bash
rangedock create gui-lab --image desktop
rangedock desktop gui-lab
rangedock burp gui-lab
```

The desktop opens through a localhost browser URL. Burp is installed inside your own container when you request it; its first launch may take time and ask you to accept its terms. The public desktop image does not bundle Burp.

If you have an OpenVPN client configuration, save it once with `rangedock vpn profile add htb --config PATH/TO/client.ovpn`, create a VPN workspace with `rangedock create vpn-lab --vpn-profile htb`, then check `rangedock vpn status vpn-lab` and `rangedock vpn logs vpn-lab`. Keep files referenced by the configuration in the same directory, using relative paths. `--vpn PATH` works too if you prefer not to save a profile.

See the [README](README.md) for all commands and the [roadmap](ROADMAP.md) for planned features.
