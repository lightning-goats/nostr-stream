import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
NAK = Path("/home/goats/.local/bin/nak")


class PrepareTests(unittest.TestCase):
    def deployment(self, directory):
        key = subprocess.run([str(NAK), "key", "generate"], capture_output=True,
                             text=True, check=True).stdout.strip()
        public = subprocess.run([str(NAK), "key", "public"], input=key,
                                capture_output=True, text=True, check=True).stdout.strip()
        home = Path(directory)
        tools = home / "bin"
        tools.mkdir()
        config = home / ".config/nak/credentials"
        config.mkdir(parents=True)
        (config / "nostr-client.cred").write_text("fake encrypted test credential")
        (config.parent / "bunker.pub").write_text(public)
        (tools / "systemd-creds").write_text("#!/bin/sh\nprintf '%s' \"$TEST_PRIVATE_KEY\"\n")
        (tools / "curl").write_text("#!/bin/sh\nexit 0\n")
        (tools / "nak").write_text('''#!/usr/bin/python3
import json, os, subprocess, sys, time
args = sys.argv[1:]
args = args[args.index("event") + 1:]
if "--sec" not in args:
    event = json.load(sys.stdin)
    relay = args[-1]
    failed = os.environ.get("TEST_FAIL_RELAYS", "").split(",")
    ok = "all" not in failed and relay not in failed
    with open(os.environ["TEST_ATTEMPTS"], "a") as output:
        output.write(json.dumps({"id": event["id"], "relay": relay, "accepted": ok}) + "\\n")
    if ok:
        with open(os.environ["TEST_EVENTS"], "a") as output:
            output.write(json.dumps(event) + "\\n")
    lost_ack = str(event["kind"]) == os.environ.get("TEST_LOST_ACK_KIND")
    sys.exit(0 if ok and not lost_ack else 1)
if "--github" not in args:
    sys.exit(4)
time.sleep(float(os.environ.get("TEST_SIGN_DELAY", "0")))
with open(os.environ["TEST_SIGN_CALLS"], "a") as output:
    output.write("sign\\n")
index = args.index("--sec")
del args[index:index+2]
relays = {"relay.primal.net", "relay.nostr.net", "nostr.oxtr.dev", "nos.lol", "relay.damus.io", "nostr.chaima.info", "lnb.bolverker.com/nostrrelay/666"}
targets = [arg for arg in args if arg in relays]
args = [arg for arg in args if arg not in relays]
env = os.environ.copy()
env["NOSTR_SECRET_KEY"] = env["TEST_PRIVATE_KEY"]
result = subprocess.run([env["REAL_NAK"], "event", *args], input="", capture_output=True, text=True, env=env)
if result.returncode == 0 and result.stdout and targets:
    with open(env["TEST_EVENTS"], "a") as output:
        output.write(result.stdout.strip() + "\\n")
if result.returncode == 0 and result.stdout:
    print(result.stdout.strip())
sys.exit(result.returncode)
''')
        for tool in tools.iterdir():
            tool.chmod(0o700)
        events = home / "events.jsonl"
        env = os.environ.copy()
        env.update(HOME=str(home), PATH=f"{tools}:/usr/bin:/bin",
                   TEST_PRIVATE_KEY=key, REAL_NAK=str(NAK), TEST_EVENTS=str(events),
                   TEST_ATTEMPTS=str(home / "attempts.jsonl"),
                   TEST_SIGN_CALLS=str(home / "sign-calls"))
        command = ["bash", str(ROOT / "bin/nostr-stream"), "prepare",
                   "https://www.youtube.com/watch?v=abcdefghijk"]
        return home, events, env, command

    def test_prepare_publishes_one_goal_and_note_without_a_second_live_event(self):
        with tempfile.TemporaryDirectory() as directory:
            home, events, env, command = self.deployment(directory)
            for attempt in range(2):
                result = subprocess.run(command, capture_output=True, text=True, env=env)
                self.assertEqual(result.returncode, 0, "prepare command did not succeed")
            published = list({event["id"]: event for event in
                              map(json.loads, events.read_text().splitlines())}.values())
            self.assertEqual([event["kind"] for event in published], [9041, 1])
            self.assertEqual(dict((tag[:2] for tag in published[1]["tags"]))["goal"], published[0]["id"])

    def test_relay_fallback_publishes_identical_signed_events(self):
        with tempfile.TemporaryDirectory() as directory:
            home, events, env, command = self.deployment(directory)
            env["TEST_FAIL_RELAYS"] = "relay.primal.net,nos.lol,relay.damus.io"
            result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((home / ".local/state/lightning-goats-stream/announced/abcdefghijk").exists())
            attempts = list(map(json.loads, (home / "attempts.jsonl").read_text().splitlines()))
            self.assertTrue(any(not x["accepted"] for x in attempts))
            self.assertTrue(any(x["accepted"] for x in attempts))
            published = list(map(json.loads, events.read_text().splitlines()))
            self.assertEqual(len({x["id"] for x in published if x["kind"] == 9041}), 1)
            self.assertEqual(len({x["id"] for x in published if x["kind"] == 1}), 1)

    def test_all_relays_failing_leave_publication_pending_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            home, events, env, command = self.deployment(directory)
            env["TEST_FAIL_RELAYS"] = "all"
            first = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
            self.assertNotEqual(first.returncode, 0)
            state = home / ".local/state/lightning-goats-stream"
            self.assertFalse((state / "announced/abcdefghijk").exists())
            self.assertFalse((state / "goals/abcdefghijk").exists())
            env.pop("TEST_FAIL_RELAYS")
            second = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertTrue((state / "announced/abcdefghijk").exists())

    def test_concurrent_recovery_checks_do_not_create_duplicate_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            home, events, env, command = self.deployment(directory)
            env["TEST_SIGN_DELAY"] = "0.2"
            workers = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, env=env) for _ in range(2)]
            for worker in workers:
                _, error = worker.communicate(timeout=30)
                self.assertEqual(worker.returncode, 0, error)
            self.assertEqual((home / "sign-calls").read_text().splitlines(), ["sign", "sign"])
            published = list(map(json.loads, events.read_text().splitlines()))
            self.assertEqual(len({x["id"] for x in published if x["kind"] == 9041}), 1)
            self.assertEqual(len({x["id"] for x in published if x["kind"] == 1}), 1)

    def test_lost_ack_reuses_the_signed_note_after_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            home, events, env, command = self.deployment(directory)
            env["TEST_LOST_ACK_KIND"] = "1"
            first = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
            self.assertNotEqual(first.returncode, 0)
            self.assertFalse((home / ".local/state/lightning-goats-stream/announced/abcdefghijk").exists())
            env.pop("TEST_LOST_ACK_KIND")
            second = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual((home / "sign-calls").read_text().splitlines(), ["sign", "sign"])
            notes = [e for e in map(json.loads, events.read_text().splitlines()) if e["kind"] == 1]
            self.assertEqual(len({e["id"] for e in notes}), 1)

    def test_failed_outbox_sync_never_sends_an_unrecoverable_event(self):
        with tempfile.TemporaryDirectory() as directory:
            home, events, env, command = self.deployment(directory)
            sync = home / "bin/sync"
            sync.write_text('#!/bin/sh\nexit 1\n')
            sync.chmod(0o700)
            result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((home / "attempts.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
