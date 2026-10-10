import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()
