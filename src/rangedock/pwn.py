"""AI-assisted CTF mode (see PWN_SPEC.md).

Phase 1 scaffolding: the authorization gate, the propose/approve/execute loop, a local
transcript, a step budget, and a stub provider. The AI proposes; a human executes. No
command runs without an explicit human decision. Model integration and passive/consequential
tier classification arrive in later phases; until then every proposal takes a single
per-command decision and commands run through the same Workbench.execute path as the console.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import urlsplit

from .config import config_dir, create_private_file
from .console import DEFAULT_CWD, forward_interrupts
from .core import RangeDockError, Workbench, valid_name

Prompt = Callable[[str], str]
Echo = Callable[[str], None]

# Read-only enumeration tools. Anything not here is treated as consequential and gets the
# strict per-command gate. Conservative on purpose: unknown tool -> consequential.
PASSIVE_TOOLS = frozenset({
    "nmap", "dig", "host", "whois", "whatweb", "nikto", "gobuster", "ffuf",
    "feroxbuster", "dirb", "wfuzz", "ping", "dnsrecon", "rg",
})
IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def classify(argv: list[str]) -> str:
    """'passive' for read-only recon, 'consequential' otherwise. Sets confirmation strength."""
    if not argv or argv[0] not in PASSIVE_TOOLS:
        return "consequential"
    # nmap NSE scripts can write to or exploit the target; treat any script use as consequential.
    if any(arg == "--script" or arg.startswith("--script=") for arg in argv[1:]):
        return "consequential"
    return "passive"


def hosts_in(argv: list[str]) -> set[str]:
    """Host-shaped arguments: IP literals and URL hosts.

    ponytail: bare hostnames are not detected (indistinguishable from filenames); this
    catches IPs and URLs, which is the real CTF shape. Tighten if bare-hostname targets matter.
    """
    hosts: set[str] = set()
    for token in argv[1:]:
        if "://" in token:
            host = urlsplit(token).hostname
            if host:
                hosts.add(host)
        elif IP_RE.match(token):
            hosts.add(token)
    return hosts


def out_of_scope(argv: list[str], target: str) -> list[str]:
    """Host-shaped arguments that are not the session target."""
    return sorted(host for host in hosts_in(argv) if host != target)


@dataclass(frozen=True)
class Proposal:
    argv: list[str]
    reasoning: str = ""


@dataclass(frozen=True)
class Decision:
    argv: list[str] | None  # None means rejected


class PwnProvider(Protocol):
    """A source of command proposals. Real providers wrap the user's chosen model."""

    def list_models(self) -> list[str]: ...

    def propose(self, session: "PwnSession") -> Proposal | None: ...


class StdinProvider:
    """Phase 1 stub: the operator types the next command. Proves the loop without a model."""

    def list_models(self) -> list[str]:
        return []

    def propose(self, session: "PwnSession") -> Proposal | None:
        try:
            line = session.prompt("propose (blank to stop)> ")
        except EOFError:
            return None
        words = shlex.split(line)
        return Proposal(words) if words else None


def transcript_path(name: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return config_dir() / "pwn" / f"{name}-{stamp}.jsonl"


class PwnSession:
    def __init__(self, bench: Workbench, name: str, *, target: str, provider: PwnProvider,
                 prompt: Prompt, echo: Echo, max_steps: int = 40):
        self.bench = bench
        self.name = valid_name(name)
        self.target = target
        self.provider = provider
        self.prompt = prompt
        self.echo = echo
        self.max_steps = max_steps
        self.steps = 0
        self.cwd = DEFAULT_CWD
        self.transcript = transcript_path(self.name)

    def record(self, event: str, **fields) -> None:
        entry = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        try:
            with self.transcript.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(entry) + "\n")
        except OSError as exc:
            raise RangeDockError(f"Cannot write transcript {self.transcript}: {exc}") from exc

    def authorize(self) -> bool:
        """Require a typed confirmation of the target before anything else happens."""
        self.echo("rangedock pwn is EXPERIMENTAL. It runs commands you approve inside the")
        self.echo("workspace against the target you name. In later versions it also sends your")
        self.echo("commands and the target's responses to a model you configure; the target's")
        self.echo("output is untrusted and could try to steer the next suggestion, so you")
        self.echo("approve every action. Use it only against systems you are authorized to test.")
        try:
            answer = self.prompt(f"Type the target to confirm you are authorized to test it:\n> ")
        except EOFError:
            answer = ""
        if answer.strip() != self.target:
            self.echo("Target not confirmed. Aborting.")
            return False
        return True

    def vet(self, argv: list[str]) -> bool:
        """Block commands that touch a host other than the target, before they can run."""
        offenders = out_of_scope(argv, self.target)
        if offenders:
            self.echo(f"Blocked: command targets {', '.join(offenders)}, not {self.target}.")
            self.record("blocked_out_of_scope", argv=argv, hosts=offenders)
            return False
        return True

    def confirm(self, proposal: Proposal, tier: str) -> Decision:
        """Show a proposal and take a single per-command decision: run, edit, or reject."""
        self.echo(f"Proposed [{tier}]: {shlex.join(proposal.argv)}")
        if proposal.reasoning:
            self.echo(f"Why: {proposal.reasoning}")
        try:
            answer = self.prompt("Run this against the target? [y/n/edit] ").strip().lower()
        except EOFError:
            return Decision(None)
        if answer in ("e", "edit"):
            try:
                edited = self.prompt("Edited command: ")
            except EOFError:
                return Decision(None)
            words = shlex.split(edited)
            return Decision(words or None)
        return Decision(proposal.argv if answer in ("y", "yes") else None)

    def execute(self, argv: list[str]) -> int:
        started = time.monotonic()
        with forward_interrupts():
            code = self.bench.execute(self.name, argv, workdir=self.cwd)
        elapsed = time.monotonic() - started
        self.echo(f"[exit {code} · {elapsed:.2f}s]")
        self.record("executed", argv=argv, exit_code=code, seconds=round(elapsed, 3))
        return code

    def run(self) -> int:
        self.bench.start(self.name)
        create_private_file(self.transcript)
        self.record("session_start", workspace=self.name, target=self.target, max_steps=self.max_steps)
        if not self.authorize():
            self.record("authorization_declined")
            return 1
        self.record("authorized", target=self.target)
        self.echo(f"Target {self.target} confirmed. Transcript: {self.transcript}")
        while self.steps < self.max_steps:
            try:
                proposal = self.provider.propose(self)
            except KeyboardInterrupt:
                self.echo("")
                break
            if proposal is None:
                break
            tier = classify(proposal.argv)
            self.record("proposed", argv=proposal.argv, reasoning=proposal.reasoning, tier=tier)
            if not self.vet(proposal.argv):
                continue
            try:
                decision = self.confirm(proposal, tier)
            except KeyboardInterrupt:
                self.echo("")
                break
            if decision.argv is None:
                self.record("rejected", argv=proposal.argv)
                continue
            if not self.vet(decision.argv):  # re-check an edited command before it runs
                continue
            self.record("approved", argv=decision.argv, edited=decision.argv != proposal.argv,
                        tier=classify(decision.argv))
            try:
                self.execute(decision.argv)
            except KeyboardInterrupt:
                self.echo("")
                continue
            self.steps += 1
        else:
            self.echo(f"Step budget reached ({self.max_steps}). Stopping.")
            self.record("budget_reached", steps=self.steps)
        self.record("session_end", steps=self.steps)
        return 0


def open_pwn(bench: Workbench, name: str, *, target: str, max_steps: int = 40) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise RangeDockError("rangedock pwn needs an interactive terminal.")
    session = PwnSession(bench, name, target=target, provider=StdinProvider(),
                         prompt=input, echo=print, max_steps=max_steps)
    return session.run()
