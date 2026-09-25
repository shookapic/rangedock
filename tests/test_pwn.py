import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import subprocess

from rangedock.config import config_dir
from rangedock.core import RangeDockError
from rangedock.pwn import (OpencodeProvider, Proposal, PwnSession, build_prompt, classify,
                           hosts_in, out_of_scope, parse_proposal)


class FakeBench:
    def __init__(self, code=0):
        self.code = code
        self.started = []
        self.executed = []

    def start(self, name):
        self.started.append(name)

    def capture(self, name, command, workdir="/workspace"):
        raise RangeDockError("no manifest in fake workspace")

    def execute(self, name, argv, workdir="/workspace"):
        self.executed.append((name, argv, workdir))
        return self.code


class ScriptedProvider:
    def __init__(self, proposals):
        self.proposals = list(proposals)

    def list_models(self):
        return []

    def propose(self, session):
        return self.proposals.pop(0) if self.proposals else None


def scripted_prompt(answers):
    queue = list(answers)

    def prompt(_text):
        if not queue:
            raise EOFError
        return queue.pop(0)

    return prompt


class PwnSessionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        patch = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.folder.name, "APPDATA": self.folder.name})
        patch.start()
        self.addCleanup(patch.stop)
        self.output = []

    def session(self, *, provider, answers, target="10.0.0.1", max_steps=40):
        return PwnSession(FakeBench(), "lab", target=target, provider=provider,
                          prompt=scripted_prompt(answers), echo=self.output.append, max_steps=max_steps)

    def transcript_events(self, session):
        return [json.loads(line) for line in session.transcript.read_text(encoding="utf-8").splitlines()]

    def test_wrong_target_aborts_before_any_command(self):
        session = self.session(provider=ScriptedProvider([Proposal(["nmap", "10.0.0.1"])]), answers=["10.9.9.9"])
        code = session.run()
        self.assertEqual(code, 1)
        self.assertEqual(session.bench.executed, [])
        events = [entry["event"] for entry in self.transcript_events(session)]
        self.assertIn("authorization_declined", events)
        self.assertNotIn("executed", events)

    def test_approved_command_runs_and_rejected_one_does_not(self):
        provider = ScriptedProvider([Proposal(["nmap", "-sV", "10.0.0.1"]), Proposal(["curl", "-I", "10.0.0.1"])])
        session = self.session(provider=provider, answers=["10.0.0.1", "y", "n"])
        code = session.run()
        self.assertEqual(code, 0)
        self.assertEqual([argv for _, argv, _ in session.bench.executed], [["nmap", "-sV", "10.0.0.1"]])
        self.assertEqual(session.steps, 1)
        events = [entry["event"] for entry in self.transcript_events(session)]
        self.assertEqual(events.count("executed"), 1)
        self.assertIn("rejected", events)

    def test_edit_replaces_the_proposed_command(self):
        provider = ScriptedProvider([Proposal(["nmap", "10.0.0.1"])])
        session = self.session(provider=provider, answers=["10.0.0.1", "edit", "id"])
        session.run()
        self.assertEqual([argv for _, argv, _ in session.bench.executed], [["id"]])
        approved = [e for e in self.transcript_events(session) if e["event"] == "approved"][0]
        self.assertTrue(approved["edited"])

    def test_step_budget_stops_the_loop(self):
        provider = ScriptedProvider([Proposal(["a", "10.0.0.1"]), Proposal(["b", "10.0.0.1"])])
        session = self.session(provider=provider, answers=["10.0.0.1", "y", "y"], max_steps=1)
        session.run()
        self.assertEqual(session.steps, 1)
        self.assertEqual(len(session.bench.executed), 1)
        events = [entry["event"] for entry in self.transcript_events(session)]
        self.assertIn("budget_reached", events)

    def test_transcript_lives_under_the_config_dir(self):
        session = self.session(provider=ScriptedProvider([]), answers=["10.0.0.1"])
        session.run()
        self.assertEqual(session.transcript.parent, config_dir() / "pwn")
        self.assertTrue(session.transcript.exists())


class ClassifyTests(unittest.TestCase):
    def test_read_only_recon_is_passive(self):
        self.assertEqual(classify(["nmap", "-sV", "10.0.0.1"]), "passive")
        self.assertEqual(classify(["gobuster", "dir", "-u", "http://10.0.0.1"]), "passive")

    def test_unknown_or_writing_tools_are_consequential(self):
        self.assertEqual(classify(["nc", "-e", "/bin/sh", "10.0.0.1"]), "consequential")
        self.assertEqual(classify(["curl", "-X", "POST", "http://10.0.0.1"]), "consequential")
        self.assertEqual(classify(["nmap", "--script", "http-put", "10.0.0.1"]), "consequential")
        self.assertEqual(classify([]), "consequential")


class ScopeTests(unittest.TestCase):
    def test_hosts_from_ips_and_urls(self):
        self.assertEqual(hosts_in(["curl", "http://10.0.0.9:8080/x", "-w", "/usr/share/list.txt"]), {"10.0.0.9"})
        self.assertEqual(hosts_in(["nmap", "10.0.0.1", "192.168.1.5"]), {"10.0.0.1", "192.168.1.5"})

    def test_out_of_scope_lists_non_target_hosts_only(self):
        self.assertEqual(out_of_scope(["nmap", "10.0.0.1"], "10.0.0.1"), [])
        self.assertEqual(out_of_scope(["curl", "http://10.0.0.1", "http://8.8.8.8"], "10.0.0.1"), ["8.8.8.8"])


class ScopeEnforcementTests(PwnSessionTests):
    def test_out_of_scope_proposal_is_blocked_before_the_prompt(self):
        provider = ScriptedProvider([Proposal(["nmap", "8.8.8.8"]), Proposal(["nmap", "-sV", "10.0.0.1"])])
        session = self.session(provider=provider, answers=["10.0.0.1", "y"])
        session.run()
        self.assertEqual([argv for _, argv, _ in session.bench.executed], [["nmap", "-sV", "10.0.0.1"]])
        events = [entry["event"] for entry in self.transcript_events(session)]
        self.assertIn("blocked_out_of_scope", events)

    def test_edited_command_is_rechecked_against_scope(self):
        provider = ScriptedProvider([Proposal(["nmap", "10.0.0.1"])])
        session = self.session(provider=provider, answers=["10.0.0.1", "edit", "curl http://8.8.8.8"])
        session.run()
        self.assertEqual(session.bench.executed, [])
        events = [entry["event"] for entry in self.transcript_events(session)]
        self.assertIn("blocked_out_of_scope", events)


def completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=["opencode"], returncode=returncode, stdout=stdout, stderr=stderr)


class ParseProposalTests(unittest.TestCase):
    def test_reads_a_fenced_json_command(self):
        text = 'Here is my plan.\n```json\n{"command": ["nmap", "-sV", "10.0.0.1"], "reasoning": "enumerate"}\n```'
        proposal = parse_proposal(text)
        self.assertEqual(proposal.argv, ["nmap", "-sV", "10.0.0.1"])
        self.assertEqual(proposal.reasoning, "enumerate")

    def test_empty_command_means_stop(self):
        self.assertIsNone(parse_proposal('```json\n{"command": []}\n```'))

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_proposal("no json here"))
        self.assertIsNone(parse_proposal('```json\n{"command": "nmap"}\n```'))


class OpencodeProviderTests(unittest.TestCase):
    def test_list_models_parses_provider_slash_model_lines(self):
        provider = OpencodeProvider(run=lambda args: completed("anthropic/claude-3-5-sonnet\nopenai/gpt-4o\nnoise\n"))
        self.assertEqual(provider.list_models(), ["anthropic/claude-3-5-sonnet", "openai/gpt-4o"])

    def test_propose_passes_model_and_parses_reply(self):
        seen = {}

        def run(args):
            seen["args"] = args
            return completed('```json\n{"command": ["id"], "reasoning": "who am i"}\n```')

        provider = OpencodeProvider(model="anthropic/x", run=run)
        session = mock.Mock(target="10.0.0.1", tool_names=set(), history=[])
        proposal = provider.propose(session)
        self.assertEqual(proposal.argv, ["id"])
        self.assertEqual(seen["args"][:3], ["run", "--model", "anthropic/x"])

    def test_failed_run_returns_none(self):
        session = mock.Mock(target="10.0.0.1", tool_names=set(), history=[], echo=lambda _t: None)
        provider = OpencodeProvider(run=lambda args: completed(returncode=1, stderr="boom"))
        self.assertIsNone(provider.propose(session))


class BuildPromptTests(unittest.TestCase):
    def test_prompt_names_target_and_history(self):
        session = mock.Mock(target="10.0.0.1", tool_names={"nmap"}, history=[(["nmap", "10.0.0.1"], 0)])
        prompt = build_prompt(session)
        self.assertIn("10.0.0.1", prompt)
        self.assertIn("nmap", prompt)
        self.assertIn("-> 0", prompt)


if __name__ == "__main__":
    unittest.main()
