# RangeDock AI-Assisted CTF Mode (`pwn`)

Status: phases 1-3 implemented (gate, loop, transcript, budget, tier + scope enforcement,
opencode provider + model selection). Provider path is verified against opencode's
documented flags and mocked in tests, but NOT yet run against a live opencode + model, and
the model does not yet see command output — treat as experimental until a live session is
validated.
Target: v0.6.x (after WireGuard and desktop maturity in v0.5)
Owner: RangeDock maintainers

## Summary

`rangedock pwn` adds an optional, opt-in, AI-assisted workflow for solving CTF machines
the user is authorized to attack. The user picks a model (from a provider that exposes a
model list) and supplies their own credential. A model proposes workspace commands with
reasoning — recon and offensive alike; a human approves, edits, or rejects each proposal
before anything runs. The model never has shell access and never chains commands on its
own.

**The hard rule: the AI proposes, a human executes.** No command runs without an explicit
human decision. Passive recon may be approved as a phase batch; every consequential
command (writes to the target, outbound connections, credential spraying, uploads,
payload-shaped tooling, exploit execution) requires per-command approval, every time, no
batching, no auto-advance on success. AI-proposing an offensive command is therefore no
more dangerous than the user typing it — the human authorizes and triggers each step.

This mode deliberately narrows the earlier project non-goal ("no AI-generated command
execution") to a human-in-the-loop form: the model generates *candidate* commands, but
every consequential execution passes through the same explicit human step that typing
into the console already requires. Fully autonomous exploitation remains a non-goal.

The feature is off by default, labeled experimental, and never surfaced by
`rangedock create`. It reuses the console's execution boundary (`Workbench.execute`)
with no new container capability.

## Why this shape

The authorization problem with a naive "point it at an IP and let it go" command is
that the tool cannot tell a CTF box from a production host, and cannot encode
authorization into an argument. This design answers that in three ways:

1. **Human authorization gate** — the user types the target to confirm authorization
   before the session starts, and confirms consequential actions individually.
2. **BYO key** — RangeDock hosts no inference, bundles no key, and adds no
   "phones home by default" path. Traffic goes only from the user's machine to the
   provider they configured.
3. **Human-in-the-loop as the security control** — target output can carry prompt
   injection, so the model's next suggestion may be attacker-influenced. The human
   confirmation gate, not the model's judgment, is what stops a bad suggestion from
   running.

## User outcome

```text
$ rangedock pwn ctf1 --target 10.10.11.5

rangedock pwn is EXPERIMENTAL. It sends your commands, their output, and the
target's responses to <provider> using your own API key. Target output is
untrusted and could try to influence the model's next suggestion — you approve
every action, so read each proposal before accepting.

Use this only against systems you are authorized to test.
Type the target to confirm you are authorized to test it:
> 10.10.11.5

Provider: anthropic · Model: <model> · Budget: 40 steps / $2.00

What are we working on?
> HTB-style box, get user and root flags

Phase: Recon (read-only, batchable)
  1. nmap -sT -sV -p- --open 10.10.11.5
  2. nmap -sC -p <from #1> 10.10.11.5
Reasoning: enumerate services before choosing an approach.
Approve this phase? [y = run in order / e = edit / n = reject / s = single-step]
```

The normal console and shell remain unchanged. `pwn` is an additional guided surface,
not a replacement.

## Goals

- Let an authorized user get AI help solving a CTF machine — recon, exploitation,
  privilege escalation, flag hunting — without leaving RangeDock's execution boundary.
- Let the user choose a model from the provider's list, not a single hardcoded model.
- Keep every execution human-approved: passive recon batchable, every consequential
  command per-command gated, with the target fixed for the session.
- Keep the user's credential out of RangeDock's trust boundary: read from env or the
  provider's own config, sent only to the chosen provider, never stored by RangeDock.
- Produce a complete local transcript of proposals, decisions, commands, and output.
- Reuse the existing workspace scope: same user, mounts, capabilities, and network.

## Non-goals

- No autonomous exploitation. The model never auto-advances to the next command on
  success, and never executes without a human decision. Offensive commands may be
  proposed, never auto-run.
- No batching of consequential commands. Each is confirmed on its own, every time.
- No RangeDock-hosted inference, bundled key, or default telemetry.
- No privilege escalation route the console does not already have: no `--privileged`,
  no extra `--cap-add`, no host networking, no writable VPN mount.
- No cross-host action. Proposals whose arguments resolve to a host other than
  `--target` are blocked before the confirmation prompt, not left to human attention.
- No claim of reliability. The model may confidently propose wrong or unsafe steps;
  the confirmation gate exists because of that, not in spite of it.
- No host shell execution. Commands run in the selected workspace, as in the console.

## Command surface

```text
rangedock pwn NAME --target HOST [--model M] [--provider P] [--max-steps N] [--max-cost USD]
rangedock pwn models [--provider P]        # list selectable models
rangedock config set pwn.provider <opencode|...>
rangedock config set pwn.model <model-id>
rangedock config set pwn.max_steps <N>
rangedock config set pwn.max_cost <USD>
```

- `NAME` is an existing workspace, resolved exactly as `console NAME` does. `pwn` never
  creates a large image or a VPN workspace from a typo.
- `--target HOST` is required and fixes the scope for the whole session.
- **Model selection.** `pwn models` lists what the provider exposes. `pwn` uses `--model`,
  else `pwn.model`, else prompts from the list. RangeDock does not hardcode one model.
- **Credential.** Read from the provider's standard env var or the provider's own config
  (e.g. opencode's existing auth). RangeDock never writes the credential to its own disk.
- With no provider configured or no credential present, `pwn` fails with an actionable
  message and runs nothing.

## Authorization and consent

- **First-run gate per workspace + target.** A non-skippable typed confirmation of the
  target string. Not a stored EULA checkbox — it is re-shown when the target changes.
- **The gate text names the provider and the untrusted-output risk once, in the UI**,
  not only in docs.
- **Session scope is immutable.** Changing `--target` starts a new session with a new
  gate and a new transcript.

## Confirmation tiers

RangeDock classifies every proposed argv against a maintained allowlist, not the model's
own label. Classification sets the confirmation strength, not whether the AI may propose.

- **Read-only / passive** (e.g. `nmap`, `curl -I`, directory brute force, `whatweb`,
  `dig`, `nikto`): may be offered as a short phase batch and approved once. Each command
  runs in order and stops on the first that fails or changes tier.
- **Consequential** (writes to the target, outbound connections, credential spraying,
  uploads, payload-shaped tooling, exploit execution): **per-command confirmation, every
  time, no batching, no exceptions, even mid-phase.** The proposal shows the exact argv
  and its reasoning; nothing runs until the human approves that specific command.
- Any command that does not match the passive allowlist is treated as consequential and
  gets the per-command gate.

## Scope enforcement

- Every proposed command is parsed; any host-shaped argument is resolved and compared to
  `--target`. A mismatch is blocked and shown to the user, and is not offered for
  confirmation.
- The model receives the target and the workspace tool manifest as context. It proposes
  one argv (or a passive batch) per turn as a structured tool call; it does not receive
  a shell, a file handle, or the ability to run anything directly.
- Command execution goes through `Workbench.execute` on the same path a console command
  takes — same container, user, mounts, capabilities, network.

## Untrusted output handling

- Target responses (banners, HTTP bodies, file contents, tool stdout/stderr) are fed
  back to the model wrapped explicitly as data, clearly delimited from instructions.
- The wrapping is a defense-in-depth measure only. The human confirmation gate is the
  control that actually prevents injected instructions from executing.

## Audit, budget, and kill switch

- **Transcript.** Every proposal, reasoning, human decision (approved / edited /
  rejected), executed argv, exit code, duration, and captured output is written to a
  per-session file on the host, following the console history storage pattern and
  honoring the same `history = false` / secret-redaction rules.
- **Budget.** `--max-steps` and `--max-cost` cap the session. Reaching either stops the
  loop and reports usage. Defaults are conservative.
- **Kill switch.** Ctrl-C aborts the current command and returns to the decision prompt;
  a second Ctrl-C exits the session. No proposal is auto-retried in a loop.

## Provider integration surface

`PwnProvider` interface:

- `list_models()` → selectable models the user can pick from. Drives `pwn models` and the
  selection prompt. No single model is hardcoded.
- `propose(context, history)` → one structured proposal (argv or passive batch +
  reasoning) plus usage. The provider does not decide execution; RangeDock classifies and
  gates.

Implementations:

- **opencode is the required first provider.** It already aggregates providers and a model
  catalog and handles auth, so RangeDock delegates model listing, selection, and inference
  to it rather than reimplementing each provider SDK. Exact invocation surface (CLI vs
  local API, model-list format, structured-proposal transport) must be verified against
  opencode before Phase 3 — it is not fixed in this spec.
- The provider dependency is an optional extra (e.g. `rangedock[pwn]`), never core. Core
  install and every existing command work without it.
- No provider call is made before the authorization gate passes.

## Implementation shape

- Keep all lifecycle and security invariants in `Workbench`; `pwn` is an adapter over
  the same execution path the console uses.
- A `PwnSession` owns the loop: build context, request a proposal, classify tier,
  enforce scope, prompt the human, execute on approval, append to the transcript, check
  budget. It does not duplicate Docker logic.
- Tier classification and scope resolution live in pure, testable functions with no
  network or Docker dependency.
- The model-facing tool schema exposes exactly one action: "propose a command". No
  filesystem, no direct exec, no multi-command chain in a single proposal beyond a
  passive batch.

## Delivery plan

### Phase 1: session skeleton, no model

`rangedock pwn NAME --target HOST` with the authorization gate, transcript, budget
counters, Ctrl-C handling, and a stub proposer that reads argv from stdin. Proves the
gate, scope enforcement, tier classification, and execution path in isolation.

### Phase 2: tier and scope enforcement

Passive-vs-consequential classification, host-scope resolution and blocking, and the
batch/per-command confirmation UX. Exit when a crafted proposal touching a non-target host
is blocked before any prompt, and consequential commands cannot be batched or auto-run.

### Phase 3: provider integration (opencode)

Add `PwnProvider` with `list_models`/`propose`, the opencode implementation behind the
optional extra, model selection UX, and the structured proposal transport. Verify
opencode's invocation surface first. Exit when a full authorized CTF session (recon through
flag) runs against a lab box with a chosen model, every consequential action per-command
approved, and a complete transcript.

### Phase 4: polish

Cost accounting accuracy, redaction review, transcript export, and docs. Keep the mode
labeled experimental until the guardrails have real-use validation.

## Release gates

- Unit tests for tier classification (including unclassifiable → consequential), scope
  resolution and cross-host blocking, budget enforcement, gate re-trigger on target
  change, and transcript redaction.
- A test proving no provider call occurs before the gate passes.
- A test proving the model-facing schema cannot express a direct exec or a
  non-target host.
- No new default capability, privileged mode, host networking, or writable VPN mount.
- Docs state the authorization requirement, the untrusted-output risk, BYO-key handling,
  and how to disable the feature entirely.
- Core install and all existing commands work without the `pwn` extra installed.

## Open decisions

- opencode's exact invocation surface: CLI subprocess vs local API, how it lists models,
  and how a structured single-command proposal is requested and returned. Verify before
  Phase 3; may need a small adapter if opencode has no structured-proposal mode.
- Exact contents of the passive allowlist (which tools/flag-patterns count as batchable
  passive vs per-command consequential), e.g. `nmap -sV` passive but `nmap --script`
  write-categories consequential.
- Whether some offensive classes should be denied outright rather than gated (e.g. mass
  credential spraying that could lock accounts), even with per-command approval.
- How to price `--max-cost` across models without embedding a stale price table; possibly
  cap on tokens only in v1 and add cost estimation later.
- Whether the transcript should be encrypted at rest, given it can contain target output
  and discovered credentials.
