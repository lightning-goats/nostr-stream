import importlib.util
import contextlib
import io
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "lightning-goats-obs"


class LauncherTests(unittest.TestCase):
    def module(self):
        self.assertTrue(SCRIPT.exists(), "OBS streaming launcher is missing")
        loader = SourceFileLoader("obs_launcher", str(SCRIPT))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        launcher = importlib.util.module_from_spec(spec)
        loader.exec_module(launcher)
        return launcher

    def test_launch_configuration_restores_nginx_route_and_preserves_previous_settings(self):
        self.assertTrue(SCRIPT.exists(), "OBS streaming launcher is missing")
        loader = SourceFileLoader("obs_launcher", str(SCRIPT))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        launcher = importlib.util.module_from_spec(spec)
        loader.exec_module(launcher)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "service.json"
            old = b'{"type":"rtmp_common","settings":{"server":"rtmps://youtube.example/live2","key":"old-test-key"}}'
            profile.write_bytes(old)
            launcher.configure_profile(profile, root / "backup")
            saved = json.loads(profile.read_text())
            self.assertEqual(saved["type"], "rtmp_custom")
            self.assertEqual(saved["settings"]["server"], "rtmp://127.0.0.1:1935/local")
            self.assertEqual(saved["settings"]["key"], "lightning-goats")
            backups = list((root / "backup").glob("service-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), old)
            self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
            launcher.configure_profile(profile, root / "backup")
            self.assertEqual(len(list((root / "backup").glob("service-*.json"))), 1)

    def test_rotated_youtube_key_is_captured_before_restoring_local_route(self):
        launcher = self.module()
        self.assertTrue(hasattr(launcher, "capture_youtube_profile"), "YouTube key capture is missing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "service.json"
            old = {"type": "rtmp_common", "settings": {"server": "rtmps://a.rtmps.youtube.com:443/live2",
                                                       "key": "rotated-test-youtube-key"}}
            profile.write_text(json.dumps(old))
            keeper = root / "youtube-service.json"
            launcher.capture_youtube_profile(profile, keeper)
            launcher.configure_profile(profile, root / "backups")
            self.assertEqual(json.loads(keeper.read_text())["settings"]["key"], "rotated-test-youtube-key")
            self.assertEqual(keeper.stat().st_mode & 0o777, 0o600)
            before = keeper.read_bytes()
            launcher.capture_youtube_profile(profile, keeper)
            self.assertEqual(keeper.read_bytes(), before)

    def test_nvidia_offload_request_preserves_the_laptop_desktop_environment(self):
        launcher = self.module()
        desktop = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0", "XDG_SESSION_TYPE": "wayland"}
        result = launcher.obs_environment(desktop)
        self.assertEqual(result["__NV_PRIME_RENDER_OFFLOAD"], "1")
        self.assertEqual(result["__GLX_VENDOR_LIBRARY_NAME"], "nvidia")
        self.assertEqual(result["XDG_SESSION_TYPE"], "x11")
        self.assertEqual(result["QT_QPA_PLATFORM"], "xcb")
        self.assertEqual(result["WAYLAND_DISPLAY"], desktop["WAYLAND_DISPLAY"])
        self.assertEqual(desktop, {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0", "XDG_SESSION_TYPE": "wayland"})

    def test_preview_hold_uses_the_unique_collection_without_auto_streaming(self):
        launcher = self.module()
        self.assertTrue(hasattr(launcher, "obs_arguments"), "preview hold interlock is missing")
        held = launcher.obs_arguments(True)
        self.assertNotIn("--startstreaming", held)
        self.assertEqual(held[held.index("--collection") + 1], "Lightning Goats")
        self.assertIn("--startstreaming", launcher.obs_arguments(False))

    def test_startup_streams_using_saved_routes_without_waiting_for_remote_preparation(self):
        launcher = self.module()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            profile = home / "snap/obs-studio/common/.config/obs-studio/basic/profiles/Untitled/service.json"
            profile.parent.mkdir(parents=True)
            profile.write_text(json.dumps({"type": "rtmp_common", "settings": {
                "server": "rtmp://a.rtmp.youtube.com/live2", "key": "test-youtube-key"}}))
            class Launched(Exception):
                pass
            launches = []
            def launch(path, arguments, environment):
                launches.append(arguments)
                raise Launched()
            with mock.patch.object(launcher.Path, "home", return_value=home), \
                    mock.patch.object(launcher.sys, "argv", [str(SCRIPT)]), \
                    mock.patch.object(launcher.socket, "create_connection"), \
                    mock.patch.object(launcher.subprocess, "run", side_effect=AssertionError(
                        "OBS startup must not wait for remote calls")), \
                    mock.patch.object(launcher.subprocess, "Popen") as worker, \
                    mock.patch.object(launcher.os, "execve", side_effect=launch):
                with self.assertRaises(Launched):
                    launcher.main()
            self.assertIn("--startstreaming", launches[0])
            self.assertEqual(json.loads(profile.read_text())["settings"]["server"],
                             "rtmp://127.0.0.1:1935/local")
            self.assertEqual(json.loads((home / ".config/nostr-stream/youtube-service.json").read_text())[
                "settings"]["key"], "test-youtube-key")
            self.assertIn("--prepare", worker.call_args.args[0])
            self.assertTrue(worker.call_args.kwargs["start_new_session"])
            log = home / ".local/state/nostr-stream-zap/obs-preparation.log"
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_failed_ingest_refresh_does_not_skip_metadata_preparation(self):
        launcher = self.module()
        self.assertTrue(hasattr(launcher, "prepare_remote"), "Independent remote preparation is missing")
        for failure in [launcher.subprocess.CompletedProcess([], 1),
                        launcher.subprocess.TimeoutExpired("nostr-stream", 100),
                        OSError("private-diagnostic-do-not-log")]:
            with self.subTest(failure=type(failure).__name__):
                output = io.StringIO()
                with mock.patch.object(launcher.subprocess, "run", side_effect=[
                        failure, launcher.subprocess.CompletedProcess([], 0)]) as run, \
                        contextlib.redirect_stderr(output):
                    self.assertFalse(launcher.prepare_remote(Path("/test-home")))
                self.assertEqual(run.call_count, 2)
                self.assertIn("metadata", run.call_args.args[0])
                self.assertNotIn("private-diagnostic", output.getvalue())

    def test_remote_preparation_reports_metadata_failure_and_success(self):
        launcher = self.module()
        self.assertTrue(hasattr(launcher, "prepare_remote"), "Independent remote preparation is missing")
        for status, expected in [(0, True), (1, False)]:
            with self.subTest(status=status), \
                    mock.patch.object(launcher.subprocess, "run", side_effect=[
                        launcher.subprocess.CompletedProcess([], 0),
                        launcher.subprocess.CompletedProcess([], status)]), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(launcher.prepare_remote(Path("/test-home")), expected)

    def test_background_worker_failure_still_launches_streaming(self):
        launcher = self.module()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            profile = home / "snap/obs-studio/common/.config/obs-studio/basic/profiles/Untitled/service.json"
            profile.parent.mkdir(parents=True)
            profile.write_text('{"type":"rtmp_custom","settings":{"server":"rtmp://127.0.0.1:1935/local","key":"lightning-goats","use_auth":false}}')
            with mock.patch.object(launcher.Path, "home", return_value=home), \
                    mock.patch.object(launcher.sys, "argv", [str(SCRIPT)]), \
                    mock.patch.object(launcher.socket, "create_connection"), \
                    mock.patch.object(launcher.subprocess, "run", side_effect=OSError()), \
                    mock.patch.object(launcher.subprocess, "Popen", side_effect=OSError()), \
                    mock.patch.object(launcher.os, "execve") as launch, \
                    contextlib.redirect_stderr(io.StringIO()):
                launcher.main()
            self.assertIn("--startstreaming", launch.call_args.args[1])

    def test_check_reports_remote_failure_without_launching_obs(self):
        launcher = self.module()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            profile = home / "snap/obs-studio/common/.config/obs-studio/basic/profiles/Untitled/service.json"
            profile.parent.mkdir(parents=True)
            profile.write_text('{"settings":{}}')
            with mock.patch.object(launcher.Path, "home", return_value=home), \
                    mock.patch.object(launcher.sys, "argv", [str(SCRIPT), "--check"]), \
                    mock.patch.object(launcher.socket, "create_connection"), \
                    mock.patch.object(launcher.subprocess, "run", return_value=
                                      launcher.subprocess.CompletedProcess([], 1)), \
                    mock.patch.object(launcher.os, "execve") as launch, \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(launcher.main(), 1)
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
