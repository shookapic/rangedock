# RangeDock Profiles and Interactive Lab Console

Status: proposed feature spec  
Target: v0.4.x and v0.5.x  
Owner: RangeDock maintainers

## Summary

RangeDock should remember VPN setups and provide an interactive terminal for a
workspace. A user should be able to save a VPN profile once, select it by name when
creating a lab, and then work from a terminal with workspace, RangeDock command, and
tool completion.

The first implementation is a fast local TUI. It is not an AI agent and it does not
send commands or history to a service. AI-assisted suggestions can be considered
later, after the local interaction model is dependable.

## User outcome

```text
$ rangedock vpn profile add htb --config ~/vpn/htb.ovpn
Saved VPN profile 'htb'.

$ rangedock create htb-box --image web --vpn-profile htb
Created htb-box with VPN profile htb.

$ rangedock console htb-box
RangeDock htb-box /workspace  [web] [VPN: htb connected]
❯ nma<Tab>
  nmap       Network exploration tool
❯ nmap -sT 10.10.10.10
```

The normal shell commands remain available. The console is an additional guided
surface for people who prefer an IDE-like terminal.

## Goals

- Save a named VPN profile and reuse it without repeating a filesystem path.
- Keep VPN configuration files and referenced credentials on the host, mounted
  read-only into the container.
- Make workspace selection, RangeDock subcommands, VPN profiles, and installed tools
  discoverable through Tab completion.
- Make a CTF workflow quick to learn: select a workspace, find a tool, run it, inspect
  output, and return to the same workspace later.
- Work on Windows, macOS, and Linux wherever the existing Docker support works.
- Keep the local product free of accounts, required telemetry, and network services.

## Non-goals

- No autonomous exploitation, target discovery, or AI-generated command execution.
- No cloud terminal, shared team state, or remote command relay.
- No automatic copying of VPN keys into a RangeDock-managed directory in the first
  version.
- No promise that every Kali command has perfect option completion. Tool completion
  starts with a maintained manifest and improves from `--help` output over time.
- No host shell execution from the console in the first version. Commands run in the
  selected workspace so the execution boundary is obvious.

## Feature A: named VPN profiles

### Commands

```text
rangedock vpn profile add NAME --config PATH [--type openvpn]
rangedock vpn profile list
rangedock vpn profile show NAME
rangedock vpn profile remove NAME

rangedock create NAME --vpn-profile PROFILE [--image PROFILE]
rangedock open NAME --vpn-profile PROFILE
rangedock vpn connect NAME [--profile PROFILE]
```

`--vpn PATH` remains supported as a direct, one-off option for scripts and backwards
compatibility. `--vpn-profile` is the preferred human workflow.

`vpn profile add` stores the resolved configuration path and its parent directory;
it does not copy or read private key contents. Relative paths inside the OpenVPN
configuration continue to resolve against that parent directory. The profile name is
validated with the same lowercase workspace-name rules used elsewhere.

`vpn profile remove` only removes the RangeDock record. It never deletes the config,
certificate, key, or credential files on disk. Removing a profile does not modify an
existing workspace that already stores the resolved VPN path in its container label.

### Profile storage

Use one local file with restrictive permissions where the platform supports them:

- Linux/macOS: `$XDG_CONFIG_HOME/rangedock/profiles.toml`, falling back to
  `~/.config/rangedock/profiles.toml`.
- Windows: `%APPDATA%\\RangeDock\\profiles.toml`.

Example:

```toml
[vpn.htb]
type = "openvpn"
config = "C:/Users/alice/vpn/htb/client.ovpn"
config_dir = "C:/Users/alice/vpn/htb"
```

The file contains paths and metadata, not private key or password contents. The CLI
must warn when a referenced file is missing and must reject a profile before container
creation if the config extension is unsupported. `profile list` prints names, types,
and whether the config exists; it never prints key contents or inline credentials.

### Workspace behavior

- A workspace created with a profile stores the resolved config path in its existing
  `dev.rangedock.vpn` label, preserving the current restart behavior.
- Starting or restarting a workspace reconnects its configured VPN as it does today.
- `vpn status` includes the profile name and process state.
- A profile change affects new workspaces only. Changing an existing workspace requires
  an explicit `rangedock vpn set NAME --profile PROFILE` command in a later milestone.
- Profile directories are mounted read-only at `/vpn`; no additional host paths are
  mounted by profile lookup.

### Profile acceptance criteria

- Add, list, show, and remove work without Docker running.
- A profile can create a VPN workspace without the user typing the config path again.
- Missing config, invalid extension, duplicate name, and invalid TOML produce clear
  errors before any container is created.
- A profile removal leaves every source file untouched.
- Existing direct `--vpn PATH` behavior and old workspaces continue to work.
- Tests cover Linux/macOS path rules, Windows paths, permissions where available, and
  no secret material in output.

## Feature B: interactive lab console

### Entry point

```text
rangedock console NAME
rangedock console NAME --profile VPN_PROFILE
rangedock console --last
```

`console` starts or reuses the selected workspace, then opens an interactive prompt.
It must fail with an actionable message when the workspace does not exist; it should
not silently create a large image or a VPN workspace from a typo.

The existing `enter` command remains the plain Bash path for scripts and users who do
not want a TUI.

### Layout

The first version should stay compact and keyboard friendly:

```text
┌ RangeDock · ctf-box · web · VPN htb connected ─────────────────────────────┐
│ command output and scrollback                                               │
│                                                                             │
├ /workspace                                                                   │
❯ nmap -sT 10.10.10.10                                                       │
└ Tab tools · Ctrl-P history · Ctrl-K command palette · Ctrl-D exit ──────────┘
```

Required interactions:

- Up/down history, reverse search, Ctrl-C cancellation, and Ctrl-D exit.
- Tab completion for workspace names, built-in commands, profiles, tool names,
  subcommands, and common tool options.
- A command palette showing actions such as `workspace info`, `vpn status`, `desktop`,
  `image list`, and `exit`.
- Clear running/stopped/VPN state in the header.
- Scrollable output with exit code and elapsed time after each command.
- Terminal resize support and a readable non-color fallback.

### Completion model

Completion is local and deterministic:

1. Complete RangeDock commands from the CLI parser and command metadata.
2. Complete workspace and VPN profile names from local Docker labels and the profile
   file.
3. Complete installed tools from a versioned image manifest generated during image
   builds. Each entry contains binary name, short description, aliases, and category.
4. For a known tool, offer maintained common options and query `tool --help` only on
   explicit request or first use. Completion must never execute a target-facing tool.
5. Fall back to the workspace shell for unknown commands and show no fabricated
   suggestions.

The manifest should be available at `/usr/share/rangedock/tools.json` inside images and
exposed through a small `rangedock tools` command for diagnostics. It must be pinned
with the image build so completion matches the image contents.

### Console execution rules

- Each entered command is passed as an argument vector when possible; quoted shell
  syntax is parsed locally with platform-appropriate rules.
- Commands run with the same user, mounts, capabilities, and network as the selected
  workspace. The console does not add privilege or host mounts.
- The first version does not interpret natural-language requests or auto-run suggested
  commands.
- History stays on the host. Add a local `history = false` setting and a `# no-save`
  suffix for commands that may contain secrets.
- A failed command returns to the prompt. It does not stop or remove the workspace.

### Implementation shape

- Keep lifecycle and security invariants in `Workbench`; the console is an adapter.
- Use a small cross-platform TUI dependency such as `prompt_toolkit` for editing,
  completion, history, and terminal handling. Keep rich rendering optional so a plain
  terminal fallback remains possible.
- Add a `ConsoleSession` that owns prompt state, completion sources, command dispatch,
  and output rendering. Do not duplicate Docker lifecycle logic.
- Keep profile persistence behind a `ProfileStore` interface so TOML validation and
  platform paths are testable without Docker.
- Do not add an AI or hosted service dependency to the core package.

## Delivery plan

### Phase 1: profiles

Implement `ProfileStore`, profile CRUD commands, `--vpn-profile`, validation, and
documentation. Preserve direct `--vpn` support. Exit when profile unit tests and a
real create/status/restart smoke test pass on Windows and Linux.

### Phase 2: console shell

Add `rangedock console NAME` with history, Ctrl-C/Ctrl-D, output capture, and a plain
fallback. Exit when a user can run a command, see its exit code, resize the terminal,
and reconnect to the same workspace.

### Phase 3: completion and palette

Add the image tool manifest, workspace/profile completion, common tool options, and
the command palette. Exit when a clean install can complete the documented CTF flow
without memorizing RangeDock subcommands.

### Phase 4: polish

Add persisted preferences, richer tool help, benchmark data, accessibility checks,
and optional desktop handoff. Revisit AI assistance only after the local console has
stable history, completion, and clear execution boundaries.

## Release gates

- Unit tests for profile parsing, path resolution, redacted output, completion, and
  command dispatch.
- Real Docker smoke tests for profile-backed workspace creation, restart reconnect,
  and profile removal preserving source files.
- Interactive smoke tests on Windows, Linux, and macOS for history, resize, Ctrl-C,
  Ctrl-D, and non-color output.
- No new default capability, privileged mode, host networking, or writable VPN mount.
- Documentation includes how to add a profile, launch the console, disable history,
  and return to the plain `enter` command.
- Existing v0.3.x commands and workspace labels remain compatible.

## Open decisions

- Confirm whether the command should be named `console` or `tui` before implementation;
  `console` is the current recommendation because it reads naturally in documentation.
- Decide whether `prompt_toolkit` is a required dependency or an optional extra after a
  Windows and macOS packaging smoke test.
- Add WireGuard profile records only when WireGuard support itself is ready; do not
  pretend an OpenVPN profile can represent it.
