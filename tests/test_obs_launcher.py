import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
from types import SimpleNamespace
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

    def test_obs_environment_preserves_wayland_without_injecting_nvidia_settings(self):
        launcher = self.module()
        desktop = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0", "XDG_SESSION_TYPE": "wayland"}
        result = launcher.obs_environment(desktop)
        self.assertNotIn("__NV_PRIME_RENDER_OFFLOAD", result)
        self.assertNotIn("__GLX_VENDOR_LIBRARY_NAME", result)
        self.assertEqual(result["XDG_SESSION_TYPE"], "wayland")
        self.assertEqual(result["WAYLAND_DISPLAY"], desktop["WAYLAND_DISPLAY"])
        self.assertEqual(desktop, {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0", "XDG_SESSION_TYPE": "wayland"})

    def test_flatpak_config_directory_uses_the_application_sandbox_path(self):
        launcher = self.module()
        home = Path("/home/example")
        self.assertEqual(launcher.obs_config_directory(home, "flatpak"),
                         home / ".var/app/com.obsproject.Studio/config/obs-studio")

    def test_obs_configuration_discovery_uses_the_only_installed_profile_and_collection(self):
        launcher = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".var/app/com.obsproject.Studio/config/obs-studio"
            (root / "basic/profiles/GoatDayProfile").mkdir(parents=True)
            (root / "basic/scenes").mkdir(parents=True)
            (root / "basic/profiles/GoatDayProfile/basic.ini").write_text("[General]\nName=GoatDayProfile\n")
            (root / "basic/scenes/GoatDayScenes.json").write_text('{"name":"GoatDayScenes"}\n')
            self.assertEqual(launcher.discover_obs_configuration(root),
                             ("GoatDayProfile", "GoatDayScenes"))

    def test_obs_configuration_fails_when_multiple_profiles_have_no_selection(self):
        launcher = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profiles = root / "basic/profiles"
            (profiles / "Morning").mkdir(parents=True)
            (profiles / "Evening").mkdir()
            scenes = root / "basic/scenes"
            scenes.mkdir(parents=True)
            (scenes / "Goats.json").write_text('{"name":"Goats"}\n')
            with self.assertRaisesRegex(RuntimeError, "profile"):
                launcher.discover_obs_configuration(root)

    def test_global_ini_selects_named_profile_and_scene_collection(self):
        launcher = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("Morning", "Evening"):
                path = root / "basic/profiles" / name
                path.mkdir(parents=True)
                (path / "basic.ini").write_text(f"[General]\nName={name}\n")
            scenes = root / "basic/scenes"
            scenes.mkdir(parents=True)
            for name in ("GoatDay", "GoatNight"):
                (scenes / f"{name}.json").write_text(json.dumps({"name": name}))
            (root / "global.ini").write_text(
                "[Basic]\nProfile=Evening\nSceneCollectionFile=GoatNight.json\n")
            self.assertEqual(launcher.discover_obs_configuration(root), ("Evening", "GoatNight"))

    def test_platform_detection_prefers_an_installed_flatpak_obs(self):
        launcher = self.module()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = launcher.detect_obs_platform(
                home, lambda name: "/usr/bin/flatpak" if name == "flatpak" else None,
                lambda *args, **kwargs: SimpleNamespace(returncode=0))
            self.assertEqual(result, ("flatpak", home / ".var/app/com.obsproject.Studio/config/obs-studio",
                                      "/usr/bin/flatpak"))

    def test_missing_obs_installation_is_reported_as_a_prerequisite_error(self):
        launcher = self.module()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "OBS was not found"):
                launcher.detect_obs_platform(Path(directory), lambda name: None,
                                             snap_path=Path(directory) / "missing-snap")

    def test_launcher_desktop_override_is_idempotent_and_does_not_add_autostart(self):
        launcher = self.module()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / "system/com.obsproject.Studio.desktop"
            source.parent.mkdir()
            source.write_text("[Desktop Entry]\nName=OBS Studio\nExec=flatpak run com.obsproject.Studio\n")
            binary = home / ".local/bin/lightning-goats-obs"
            target = home / ".local/share/applications/com.obsproject.Studio.desktop"
            target.parent.mkdir(parents=True)
            target.write_text("[Desktop Entry]\nName=Old custom OBS\nExec=obs\n")
            launcher.write_desktop_integration(home, binary, source)
            self.assertIn(f"Exec={binary}", target.read_text())
            self.assertFalse((home / ".config/autostart").exists())
            backups = list((home / ".local/state/nostr-stream-zap/desktop-backups").glob("*"))
            launcher.write_desktop_integration(home, binary, source)
            self.assertEqual(len(list((home / ".local/state/nostr-stream-zap/desktop-backups").glob("*"))), 1)
            self.assertEqual(source.read_text(), "[Desktop Entry]\nName=OBS Studio\nExec=flatpak run com.obsproject.Studio\n")
            self.assertEqual(len(backups), 1)

    def test_existing_obs_autostart_is_retargeted_without_creating_a_second_entry(self):
        launcher = self.module()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / "system/obs.desktop"
            source.parent.mkdir()
            source.write_text("[Desktop Entry]\nName=OBS\nExec=obs\n")
            auto = home / ".config/autostart/obs.desktop"
            auto.parent.mkdir(parents=True)
            auto.write_text("[Desktop Entry]\nName=OBS\nExec=flatpak run com.obsproject.Studio\n")
            binary = home / ".local/bin/lightning-goats-obs"
            launcher.write_desktop_integration(home, binary, source)
            self.assertIn(f"Exec={binary}", auto.read_text())
            self.assertEqual(len(list(auto.parent.glob("*.desktop"))), 1)

    def test_changing_service_destination_preserves_scene_collection_bytes(self):
        launcher = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene = root / "GoatScenes.json"
            original_scene = b'{"name":"GoatScenes","sources":[{"name":"Camera","id":"browser_source"}]}\n'
            scene.write_bytes(original_scene)
            profile = root / "service.json"
            profile.write_text('{"type":"rtmp_common","settings":{"server":"rtmp://example.org/live","key":"test-stream-key"}}')
            launcher.configure_profile(profile, root / "backups")
            self.assertEqual(scene.read_bytes(), original_scene)

    def test_flatpak_launch_arguments_keep_the_discovered_obs_names(self):
        launcher = self.module()
        args = launcher.obs_arguments(False, "GoatDayProfile", "GoatDayScenes", "flatpak")
        self.assertEqual(args[:3], ["flatpak", "run", "com.obsproject.Studio"])
        self.assertEqual(args[args.index("--profile") + 1], "GoatDayProfile")
        self.assertEqual(args[args.index("--collection") + 1], "GoatDayScenes")
        self.assertIn("--startstreaming", args)

    def test_preview_hold_uses_the_unique_collection_without_auto_streaming(self):
        launcher = self.module()
        self.assertTrue(hasattr(launcher, "obs_arguments"), "preview hold interlock is missing")
        held = launcher.obs_arguments(True, "Profile A", "Collection B", "flatpak")
        self.assertNotIn("--startstreaming", held)
        self.assertEqual(held[held.index("--collection") + 1], "Collection B")
        self.assertIn("--startstreaming", launcher.obs_arguments(False, "Profile A", "Collection B", "flatpak"))


if __name__ == "__main__":
    unittest.main()
