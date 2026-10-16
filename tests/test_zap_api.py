import base64
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import tempfile
import unittest
from unittest.mock import patch
import subprocess


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "nostr-stream-zap"
HOST = "a" * 64
STREAM = "87a48d04-ea92-4d2d-a17b-463bfe8787ae"
SERVICE = "https://api-core.zap.stream/api/v1"


def module(case):
    case.assertTrue(SCRIPT.exists(), "zap.stream API integration is missing")
    loader = SourceFileLoader("zap_api", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


class ApiTests(unittest.TestCase):
    def test_event_discovery_keeps_successful_relay_results_when_another_times_out(self):
        zap = module(self)
        class Signer:
            nak = Path("/test/nak")
            public_key = HOST
        event = self.event()
        def read(command, **kwargs):
            if command[-1] == "wss://working.example":
                return subprocess.CompletedProcess(command, 0, json.dumps(event) + "\n", "")
            raise subprocess.TimeoutExpired(command, 8)
        with patch.object(zap, "RELAYS", ("wss://working.example", "wss://unavailable.example")), \
                patch.object(zap.subprocess, "run", side_effect=read):
            self.assertEqual(zap.read_events(Signer()), [event])

    def test_patch_authentication_covers_the_exact_http_body(self):
        zap = module(self)
        captured = []

        class Handler(BaseHTTPRequestHandler):
            def do_PATCH(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                auth = json.loads(base64.b64decode(self.headers["Authorization"].split()[1]))
                captured.append((self.path, body, auth, self.headers["User-Agent"]))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}/api/v1"

        def sign(tags):
            return {"kind": 27235, "pubkey": HOST, "tags": tags, "content": ""}

        api = zap.ZapApi(base, sign)
        api.request("PATCH", "event", {"title": "⚡ Goats", "tags": ["goats"]})
        path, body, event, agent = captured[0]
        self.assertEqual(path, "/api/v1/event")
        self.assertEqual(json.loads(body), {"title": "⚡ Goats", "tags": ["goats"]})
        self.assertEqual(dict(event["tags"])["u"], base + "/event")
        self.assertEqual(dict(event["tags"])["method"], "PATCH")
        self.assertEqual(dict(event["tags"])["payload"], hashlib.sha256(body).hexdigest())
        self.assertTrue(agent.startswith("nostr-stream/"))

    def test_account_output_redacts_nested_keys(self):
        zap = module(self)
        result = zap.redact({"balance": 999, "endpoints": [{"key": "private-ingest-key"}],
                             "nested": {"password": "private-password"}})
        self.assertEqual(result["balance"], 999)
        self.assertNotIn("private-ingest-key", json.dumps(result))
        self.assertNotIn("private-password", json.dumps(result))

    def test_ingest_refresh_uses_the_current_basic_endpoint_and_preserves_youtube_key(self):
        zap = module(self)
        self.assertTrue(hasattr(zap, "ingest_destinations"), "current account ingest selection is missing")
        account = {"endpoints": [
            {"name": "RTMP-Good", "url": "rtmp://in.uk.zap.stream:1935/good", "key": "good-key"},
            {"name": "RTMP-Basic", "url": "rtmp://in.uk.zap.stream:1935/basic", "key": "current-key"}]}
        youtube = {"settings": {"key": "saved-youtube-key"}}
        self.assertEqual(zap.ingest_destinations(account, youtube), {
            "youtube": {"server": "rtmp://a.rtmp.youtube.com/live2", "key": "saved-youtube-key"},
            "zap": {"server": "rtmp://in.uk.zap.stream:1935/basic", "key": "current-key"}})

    def test_stat_only_reports_the_selected_publisher(self):
        zap = module(self)
        xml = b"""<rtmp><server><application><name>local</name><live>
          <stream><name>other</name><publishing/></stream>
          <stream><name>lightning-goats</name><client><id>1</id></client></stream>
        </live></application></server></rtmp>"""
        self.assertFalse(zap.is_publishing(xml))
        xml = xml.replace(b"<client><id>1</id></client>", b"<publishing/>")
        self.assertTrue(zap.is_publishing(xml))

    def event(self, status="live", timestamp=100):
        return {"kind": 30311, "pubkey": "b" * 64, "created_at": timestamp,
                "tags": [["d", STREAM], ["status", status], ["p", HOST, "", "host"],
                         ["service", SERVICE],
                         ["streaming", f"https://cdn.zap.stream/{STREAM}/index.m3u8"]]}

    def test_latest_ended_event_overrides_an_older_live_version(self):
        zap = module(self)
        self.assertIsNone(zap.find_live_event(
            [self.event(), self.event("ended", 101)], HOST, SERVICE))

    def test_live_event_must_match_our_host_and_provider(self):
        zap = module(self)
        self.assertEqual(zap.find_live_event([self.event()], HOST, SERVICE)["stream_id"], STREAM)
        self.assertIsNone(zap.find_live_event([self.event()], "c" * 64, SERVICE))
        self.assertIsNone(zap.find_live_event([self.event()], HOST, "https://other.example/api/v1"))

    def test_regional_provider_event_selects_https_playback_among_multiple_transports(self):
        zap = module(self)
        event = self.event()
        event["tags"] = [tag for tag in event["tags"] if tag[0] != "service"]
        event["tags"] += [["service", "https://api-uk.zap.stream/api/v1"],
                          ["streaming", "moq://api-uk.zap.stream:1443/"]]
        live = zap.find_live_event([event], HOST, "https://api-core.zap.stream/api/v1")
        self.assertIsNotNone(live)
        self.assertEqual(live["playback"], f"https://cdn.zap.stream/{STREAM}/index.m3u8")

    def test_metadata_rejects_unknown_fields_and_invalid_tags(self):
        zap = module(self)
        with self.assertRaises(ValueError):
            zap.validate_metadata({"title": "Goats", "key": "unwanted-secret"})
        with self.assertRaises(ValueError):
            zap.validate_metadata({"tags": "goats"})

    def test_sync_updates_the_existing_zap_stream_and_survives_restart(self):
        zap = module(self)
        self.assertTrue(hasattr(zap, "Synchronizer"), "OBS metadata synchronization is missing")
        requests = []

        class Provider:
            def request(self, method, path, data):
                requests.append((method, path, data))
                return {}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            goals = root / "goals"
            goals.mkdir()
            (goals / "abcdefghijk").write_text("c" * 64)
            program = root / "prepare"
            program.write_text("#!/bin/sh\nprintf 'prepare\\n' >> \"$0.calls\"\n")
            program.chmod(0o700)
            metadata = {"title": "Goats", "tags": ["cyberherd"]}
            event = {"stream_id": STREAM, "playback": "https://cdn.zap.stream/live.m3u8"}
            watcher = zap.Synchronizer(Provider(), program, state, goals)
            watcher.sync("https://www.youtube.com/watch?v=abcdefghijk", event, metadata)
            restarted = zap.Synchronizer(Provider(), program, state, goals)
            restarted.sync("https://www.youtube.com/watch?v=abcdefghijk", event, metadata)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0], ("PATCH", "event", {
                "title": "Goats", "tags": ["cyberherd"], "id": STREAM, "goal": "c" * 64}))
            self.assertEqual(program.with_suffix(".calls").read_text(), "prepare\n")
            self.assertEqual(json.loads(state.read_text())["playback"], event["playback"])

    def test_failed_provider_update_is_retried_without_marking_success(self):
        zap = module(self)
        self.assertTrue(hasattr(zap, "Synchronizer"), "OBS metadata synchronization is missing")

        class UnavailableProvider:
            def request(self, *args):
                raise zap.ZapError("temporary API outage")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            goals = root / "goals"
            goals.mkdir()
            (goals / "abcdefghijk").write_text("c" * 64)
            program = root / "prepare"
            program.write_text("#!/bin/sh\nexit 0\n")
            program.chmod(0o700)
            watcher = zap.Synchronizer(UnavailableProvider(), program, root / "state.json", goals)
            with self.assertRaises(zap.ZapError):
                watcher.sync("https://www.youtube.com/watch?v=abcdefghijk",
                             {"stream_id": STREAM, "playback": "https://example.com/live.m3u8"},
                             {"title": "Goats"})
            self.assertFalse((root / "state.json").exists())

    def test_live_metadata_is_refreshed_without_reannouncing_the_stream(self):
        zap = module(self)
        requests = []

        class Provider:
            def request(self, *args):
                requests.append(args)
                return {}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            goals = root / "goals"
            goals.mkdir()
            (goals / "abcdefghijk").write_text("c" * 64)
            program = root / "prepare"
            program.write_text("#!/bin/sh\nprintf 'prepare\\n' >> \"$0.calls\"\n")
            program.chmod(0o700)
            state = root / "state.json"
            event = {"stream_id": STREAM, "playback": "https://cdn.zap.stream/live.m3u8"}
            metadata = {"title": "Goats"}
            url = "https://www.youtube.com/watch?v=abcdefghijk"
            first = zap.Synchronizer(Provider(), program, state, goals)
            first.sync(url, event, metadata)
            saved = json.loads(state.read_text())
            saved["updated_at"] = 0
            state.write_text(json.dumps(saved))
            restarted = zap.Synchronizer(Provider(), program, state, goals)
            restarted.sync(url, event, metadata)
            self.assertEqual(len(requests), 2)
            self.assertEqual(program.with_suffix(".calls").read_text(), "prepare\n")

    def test_youtube_lookup_returns_thumbnail_without_an_extra_extraction(self):
        zap = module(self)
        info = {"status": "is_live", "id": "abcdefghijk",
                "thumbnail": "https://i.ytimg.com/vi/abcdefghijk/maxresdefault_live.jpg"}
        result = subprocess.CompletedProcess([], 0, json.dumps(info) + "\n", "")
        with patch.object(zap.subprocess, "run", return_value=result) as run:
            self.assertEqual(zap.youtube_state(Path("/home/test"), include_thumbnail=True),
                             ("is_live", "https://www.youtube.com/watch?v=abcdefghijk", info["thumbnail"]))
            self.assertEqual(run.call_count, 1)

    def test_youtube_lookup_preserves_status_contract_and_handles_missing_thumbnail(self):
        zap = module(self)
        for thumbnail in [None, "NA", "http://example.com/image.jpg", "https://[invalid"]:
            info = {"status": "was_live", "id": "abcdefghijk", "thumbnail": thumbnail}
            result = subprocess.CompletedProcess([], 0, json.dumps(info) + "\n", "")
            with patch.object(zap.subprocess, "run", return_value=result):
                self.assertEqual(zap.youtube_state(Path("/home/test")),
                                 ("was_live", "https://www.youtube.com/watch?v=abcdefghijk"))
                self.assertEqual(zap.youtube_state(Path("/home/test"), include_thumbnail=True)[2],
                                 "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg")

    def test_youtube_thumbnail_updates_existing_live_event_without_duplicate_announcement(self):
        zap = module(self)
        requests = []
        class Provider:
            def request(self, method, path, data):
                requests.append(data)
                return {}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "metadata.json"
            config.write_text('{"title":"Goats","image":"https://example.com/old-logo.png"}')
            goals = root / "goals"
            goals.mkdir()
            (goals / "abcdefghijk").write_text("c" * 64)
            program = root / "prepare"
            program.write_text("#!/bin/sh\nprintf 'prepare\\n' >> \"$0.calls\"\n")
            program.chmod(0o700)
            sync = zap.Synchronizer(Provider(), program, root / "state.json", goals)
            thumbnail = "https://i.ytimg.com/vi/abcdefghijk/maxresdefault_live.jpg"
            watcher = zap.Watcher(sync.api, sync, config, lambda: True,
                                  lambda: ("is_live", "https://www.youtube.com/watch?v=abcdefghijk", thumbnail),
                                  lambda: [self.event()], HOST, SERVICE)
            watcher.tick()
            watcher.tick()
            live_updates = [data for data in requests if data.get("id") == STREAM]
            self.assertEqual(len(live_updates), 1)
            self.assertEqual(live_updates[0]["image"], thumbnail)
            self.assertEqual(live_updates[0]["goal"], "c" * 64)
            self.assertEqual(sync.state["metadata"]["image"], thumbnail)
            self.assertEqual(program.with_suffix(".calls").read_text(), "prepare\n")

    def test_watcher_waits_for_obs_without_creating_an_announcement(self):
        zap = module(self)
        self.assertTrue(hasattr(zap, "Watcher"), "nginx stream observer is missing")
        requests = []

        class Provider:
            def request(self, method, path, data):
                requests.append((method, path, data))
                return {}

        def unused():
            self.fail("Idle OBS must not resolve YouTube or publish Nostr stream notes")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "metadata.json"
            config.write_text('{"title":"Goats"}')
            sync = zap.Synchronizer(Provider(), root / "no-program-needed", root / "state.json", root / "goals")
            watcher = zap.Watcher(sync.api, sync, config, lambda: False, unused, unused, HOST, SERVICE)
            watcher.tick()
            watcher.tick()
            self.assertEqual(requests, [("PATCH", "event", {"title": "Goats", "goal": ""})])
            self.assertFalse((root / "state.json").exists())

    def test_watcher_updates_live_metadata_only_after_local_publishing(self):
        zap = module(self)
        self.assertTrue(hasattr(zap, "Watcher"), "nginx stream observer is missing")
        requests = []

        class Provider:
            def request(self, method, path, data):
                requests.append(data)
                return {}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "metadata.json"
            config.write_text('{"title":"Goats"}')
            goals = root / "goals"
            goals.mkdir()
            (goals / "abcdefghijk").write_text("c" * 64)
            program = root / "prepare"
            program.write_text("#!/bin/sh\nexit 0\n")
            program.chmod(0o700)
            sync = zap.Synchronizer(Provider(), program, root / "state.json", goals)
            watcher = zap.Watcher(sync.api, sync, config, lambda: True,
                                  lambda: ("is_live", "https://www.youtube.com/watch?v=abcdefghijk"),
                                  lambda: [self.event()], HOST, SERVICE)
            watcher.tick()
            self.assertEqual(requests[-1]["id"], STREAM)
            self.assertEqual(requests[-1]["goal"], "c" * 64)

    def test_missing_provider_event_does_not_block_timed_announcement_retry(self):
        zap = module(self)
        class Provider:
            def request(self, *args):
                return {}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "metadata.json"
            config.write_text('{"title":"Goats"}')
            goals = root / "goals"
            goals.mkdir()
            (goals / "abcdefghijk").write_text("c" * 64)
            program = root / "prepare"
            program.write_text('''#!/bin/sh
printf 'attempt\\n' >> "$0.calls"
if [ ! -f "$0.recovered" ]; then exit 1; fi
touch "$0.published"
''')
            program.chmod(0o700)
            sync = zap.Synchronizer(Provider(), program, root / "state.json", goals)
            now = [0]
            watcher = zap.Watcher(sync.api, sync, config, lambda: True,
                                  lambda: ("is_live", "https://www.youtube.com/watch?v=abcdefghijk"),
                                  lambda: [], HOST, SERVICE, clock=lambda: now[0])
            with self.assertRaises(zap.ZapError):
                watcher.tick()
            self.assertEqual(program.with_suffix(".calls").read_text(), "attempt\n")
            now[0] = 29
            watcher.tick()
            self.assertEqual(program.with_suffix(".calls").read_text(), "attempt\n")
            program.with_suffix(".recovered").touch()
            now[0] = 30
            watcher.tick()
            self.assertTrue(program.with_suffix(".published").exists())
            self.assertEqual(program.with_suffix(".calls").read_text(), "attempt\nattempt\n")
            now[0] = 60
            watcher.tick()
            self.assertEqual(program.with_suffix(".calls").read_text(), "attempt\nattempt\n")

    def test_provider_api_outage_does_not_block_stream_announcement(self):
        zap = module(self)
        class Provider:
            def request(self, *args):
                raise zap.ZapError("provider API unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "metadata.json"
            config.write_text('{"title":"Goats"}')
            goals = root / "goals"
            goals.mkdir()
            (goals / "abcdefghijk").write_text("c" * 64)
            program = root / "prepare"
            program.write_text('#!/bin/sh\ntouch "$0.published"\n')
            program.chmod(0o700)
            sync = zap.Synchronizer(Provider(), program, root / "state.json", goals)
            watcher = zap.Watcher(sync.api, sync, config, lambda: True,
                                  lambda: ("is_live", "https://www.youtube.com/watch?v=abcdefghijk"),
                                  lambda: [], HOST, SERVICE)
            with self.assertRaises(zap.ZapError):
                watcher.tick()
            self.assertTrue(program.with_suffix(".published").exists())

    def test_goal_retirement_allows_preparing_the_same_broadcast_again(self):
        zap = module(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            goals = root / "goals"
            goals.mkdir()
            (goals / "abcdefghijk").write_text("c" * 64)
            program = root / "prepare"
            program.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "$0.calls"\n')
            program.chmod(0o700)
            sync = zap.Synchronizer(None, program, root / "state.json", goals)
            url = "https://www.youtube.com/watch?v=abcdefghijk"
            sync.prepare(url)
            sync.delete_goal(url)
            sync.prepare(url)
            self.assertEqual(program.with_suffix(".calls").read_text().splitlines(),
                             ["prepare", "delete-goal", "prepare"])

    def test_goal_retirement_waits_for_confirmed_youtube_end(self):
        zap = module(self)
        self.assertTrue(hasattr(zap, "Watcher"), "nginx stream observer is missing")

        class Provider:
            def request(self, *args):
                return {}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "metadata.json"
            config.write_text('{"title":"Goats"}')
            goals = root / "goals"
            goals.mkdir()
            (goals / "abcdefghijk").write_text("c" * 64)
            program = root / "retire"
            program.write_text("#!/bin/sh\nprintf '%s\\n' \"$1\" > \"$0.called\"\n")
            program.chmod(0o700)
            state = root / "state.json"
            state.write_text('{"url":"https://www.youtube.com/watch?v=abcdefghijk"}')
            sync = zap.Synchronizer(Provider(), program, state, goals)
            statuses = iter(["is_live", "was_live", "was_live", "was_live"])
            watcher = zap.Watcher(sync.api, sync, config, lambda: False,
                                  lambda: (next(statuses), "", ""), lambda: [], HOST, SERVICE)
            for _ in range(3):
                watcher.tick()
                self.assertTrue(state.exists())
            watcher.tick()
            self.assertFalse(state.exists())
            self.assertEqual(program.with_suffix(".called").read_text().strip(), "delete-goal")

    def test_status_failure_interrupts_consecutive_offline_confirmation(self):
        zap = module(self)

        class Provider:
            def request(self, *args):
                return {}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "metadata.json"
            config.write_text('{"title":"Goats"}')
            goals = root / "goals"
            goals.mkdir()
            (goals / "abcdefghijk").write_text("c" * 64)
            program = root / "retire"
            program.write_text("#!/bin/sh\nexit 0\n")
            program.chmod(0o700)
            state = root / "state.json"
            state.write_text('{"url":"https://www.youtube.com/watch?v=abcdefghijk"}')
            sync = zap.Synchronizer(Provider(), program, state, goals)
            statuses = iter(["was_live", "was_live", None, "was_live"])

            def youtube():
                status = next(statuses)
                if status is None:
                    raise zap.ZapError("temporary extraction failure")
                return status, ""

            watcher = zap.Watcher(sync.api, sync, config, lambda: False, youtube, lambda: [], HOST, SERVICE)
            watcher.tick()
            watcher.tick()
            with self.assertRaises(zap.ZapError):
                watcher.tick()
            watcher.tick()
            self.assertTrue(state.exists(), "an indeterminate check must restart offline confirmation")

    def test_previous_goal_is_retained_for_confirmation_after_new_broadcast(self):
        zap = module(self)

        class Provider:
            def request(self, *args):
                return {}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "metadata.json"
            config.write_text('{"title":"Goats"}')
            goals = root / "goals"
            goals.mkdir()
            (goals / "abcdefghijk").write_text("c" * 64)
            (goals / "zyxwvutsrqp").write_text("d" * 64)
            program = root / "prepare"
            program.write_text("#!/bin/sh\nprintf '%s\\n' \"$1\" >> \"$0.calls\"\n")
            program.chmod(0o700)
            state = root / "state.json"
            event = {"stream_id": STREAM, "playback": "https://cdn.zap.stream/live.m3u8"}
            first_url = "https://www.youtube.com/watch?v=abcdefghijk"
            next_url = "https://www.youtube.com/watch?v=zyxwvutsrqp"
            sync = zap.Synchronizer(Provider(), program, state, goals)
            sync.sync(first_url, event, {"title": "Goats"})
            sync.sync(next_url, event, {"title": "Goats"})
            self.assertEqual(json.loads(state.read_text()).get("pending_goals"), [first_url])
            restarted = zap.Synchronizer(Provider(), program, state, goals)
            watcher = zap.Watcher(restarted.api, restarted, config, lambda: False,
                                  lambda: ("is_live", next_url), lambda: [], HOST, SERVICE,
                                  youtube_by_url=lambda url: ("was_live", url))
            watcher.tick()
            watcher.tick()
            config.write_text("invalid JSON")
            with self.assertRaises(ValueError):
                watcher.tick()
            config.write_text('{"title":"Goats"}')
            watcher.tick()
            self.assertEqual(json.loads(state.read_text()).get("pending_goals"), [first_url])
            for _ in range(2):
                watcher.tick()
            saved = json.loads(state.read_text())
            self.assertEqual(saved["url"], next_url)
            self.assertEqual(saved.get("pending_goals"), [])
            self.assertEqual(program.with_suffix(".calls").read_text().splitlines(),
                             ["prepare", "prepare", "delete-goal"])


if __name__ == "__main__":
    unittest.main()
