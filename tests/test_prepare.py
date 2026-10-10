import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
NAK = Path(shutil.which("nak") or "/home/goats/.local/bin/nak")


class PrepareTests(unittest.TestCase):
    def test_prepare_publishes_one_goal_and_note_without_a_second_live_event(self):
        key = subprocess.run([str(NAK), "key", "generate"], capture_output=True,
                             text=True, check=True).stdout.strip()
        public = subprocess.run([str(NAK), "key", "public"], input=key,
                                capture_output=True, text=True, check=True).stdout.strip()
        with tempfile.TemporaryDirectory() as directory:
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
import json, os, subprocess, sys
args = sys.argv[1:]
if "--github" in args:
    print("installed nak does not support the obsolete --github option", file=sys.stderr)
    sys.exit(4)
args = args[args.index("event") + 1:]
index = args.index("--sec")
del args[index:index+2]
args = [arg for arg in args if arg not in {"nos.lol", "relay.damus.io", "nostr.chaima.info", "lnb.bolverker.com/nostrrelay/666"}]
env = os.environ.copy()
env["NOSTR_SECRET_KEY"] = env["TEST_PRIVATE_KEY"]
result = subprocess.run([env["REAL_NAK"], "event", *args], input="", capture_output=True, text=True, env=env)
if result.returncode == 0 and result.stdout:
    with open(env["TEST_EVENTS"], "a") as output:
        output.write(result.stdout.strip() + "\\n")
    print(result.stdout.strip())
sys.exit(result.returncode)
''')
            for tool in tools.iterdir():
                tool.chmod(0o700)
            events = home / "events.jsonl"
            env = os.environ.copy()
            env.update(HOME=str(home), PATH=f"{tools}:/usr/bin:/bin",
                       TEST_PRIVATE_KEY=key, REAL_NAK=str(NAK), TEST_EVENTS=str(events))
            command = ["bash", str(ROOT / "bin/nostr-stream"), "prepare",
                       "https://www.youtube.com/watch?v=abcdefghijk"]
            for attempt in range(2):
                result = subprocess.run(command, capture_output=True, text=True, env=env)
                self.assertEqual(result.returncode, 0, f"prepare command did not succeed: {result.stderr}")
            published = [json.loads(line) for line in events.read_text().splitlines()]
            self.assertEqual([event["kind"] for event in published], [9041, 1])
            self.assertEqual(dict((tag[:2] for tag in published[1]["tags"]))["goal"], published[0]["id"])


if __name__ == "__main__":
    unittest.main()
