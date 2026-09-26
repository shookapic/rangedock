# RangeDock MCP server

Status: implemented in v0.4.2

## Purpose

Let an MCP client inspect RangeDock and, when the operator explicitly enables it,
run commands in one existing workspace. The server is a local stdio process. It
uses `Workbench`, `ProfileStore`, and the image tool catalog directly; it does not
invoke the interactive CLI or the experimental `pwn` mode.

## Launch

```text
rangedock-mcp                         # discovery only
rangedock-mcp --workspace ctf-lab     # discovery limited to one workspace
rangedock-mcp --workspace ctf-lab --allow-exec
```

Install the optional dependency from a checkout with `python -m pip install -e
'.[mcp]'`. For an existing pipx install, use `pipx inject rangedock 'mcp>=2,<3'`;
for a new uv tool install, use `uv tool install --with mcp
git+https://github.com/shookapic/rangedock.git`. The normal RangeDock install
does not need the MCP SDK. The server writes protocol messages to stdout and
diagnostics to stderr.

## Tools

Always available:

- `list_workspaces`: managed workspace names, status, image profile, and VPN
  profile name. A scoped server returns only its selected workspace.
- `workspace_info(name)`: the same structured status for one workspace.
- `list_vpn_profiles`: profile names, types, and availability. It does not return
  configuration paths, certificates, keys, or credentials.
- `vpn_status(name)`: connection state for an existing workspace.
- `list_tools(name)`: names, categories, and descriptions from the selected
  workspace's tool manifest. It requires a running workspace and never starts
  one merely to answer a read request.
- `tool_info(name, tool_name)`: manifest description and common options for one tool.

Only with `--workspace NAME --allow-exec`:

- `start_workspace`: start the selected workspace.
- `stop_workspace`: stop the selected workspace; host files remain.
- `run_command(argv, timeout_seconds=30)`: run one argv vector inside the selected
  workspace and return stdout, stderr, exit code, duration, timeout state, and
  truncation state. It requires a running workspace and uses `/workspace` as cwd.

The execution grant covers arbitrary commands in that container, including shells.
Commands can change the mounted host workspace and use the container's network.
The server does not infer target authorization from an IP argument. The operator
chooses the workspace and enables execution when configuring the MCP client.

## Limits and invariants

- Existing RangeDock ownership labels are checked by `Workbench` on every named
  workspace operation. No arbitrary Docker container or host shell is exposed.
- Execution has a 1–120 second inner container timeout, a slightly longer host
  timeout, a fixed 64 KiB combined output limit, and bounded argv size.
- A read tool never starts a stopped workspace. Tool catalog reads fail clearly
  until the workspace is started.
- No create, remove, image build/pull, VPN profile mutation, VPN log reading,
  remote HTTP transport, or `pwn` tools in this release.
- MCP tool annotations describe read/write behavior for clients; server-side
  gating enforces the actual execution grant.

## Acceptance

1. A standard install still imports and runs the CLI without `mcp` installed.
2. An MCP client can connect over stdio, list the default tools, and get
   structured workspace/profile data without changing Docker state.
3. The execution tools are absent in discovery mode and present only with the
   explicit workspace grant.
4. A command returns separate stdout/stderr, exit code, and a bounded result;
   timeout and oversized output are observable.
5. A scoped server refuses another workspace name and does not expose its data.
6. A real Docker smoke test runs a harmless command in an existing RangeDock
   workspace through the MCP tool and confirms no host process is launched by it.
