import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import tempfile
import threading
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "lightning-goats-nginx-routes"


class RoutesTests(unittest.TestCase):
    def module(self):
        self.assertTrue(SCRIPT.exists(), "dynamic nginx route updater is missing")
        loader = SourceFileLoader("routes", str(SCRIPT))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        result = importlib.util.module_from_spec(spec)
        loader.exec_module(result)
        return result

    def destinations(self):
        return {"youtube": {"server": "rtmp://a.rtmp.youtube.com/live2", "key": "youtube-test-key-123"},
                "zap": {"server": "rtmp://in.uk.zap.stream:1935/basic", "key": "zap-test-key-123456"}}

    def test_new_key_updates_the_forward_without_putting_the_key_in_arguments(self):
        routes = self.module()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "destinations.conf"
            target.write_text("old destinations")
            changes = []
            changed = routes.update_routes(self.destinations(), target,
                                           lambda: changes.append("validate"),
                                           lambda: changes.append("reload"))
            self.assertTrue(changed)
            self.assertEqual(changes, ["validate", "reload"])
            self.assertIn("push rtmp://in.uk.zap.stream:1935/basic/zap-test-key-123456;", target.read_text())
            self.assertIn("push rtmp://a.rtmp.youtube.com/live2/youtube-test-key-123;", target.read_text())
            self.assertEqual(target.read_text().count("\npush "), 2)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertFalse(routes.update_routes(self.destinations(), target,
                                                 lambda: changes.append("validate"),
                                                 lambda: changes.append("reload")))
            self.assertEqual(changes, ["validate", "reload"])

    def test_failed_nginx_validation_restores_previous_destinations(self):
        routes = self.module()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "destinations.conf"
            target.write_text("old destinations")

            def fail():
                raise RuntimeError("nginx validation failed")

            with self.assertRaises(RuntimeError):
                routes.update_routes(self.destinations(), target, fail, lambda: self.fail("must not reload"))
            self.assertEqual(target.read_text(), "old destinations")

    def test_failed_reload_reapplies_restored_destinations(self):
        routes = self.module()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "destinations.conf"
            target.write_text("old destinations")
            runtime = []
            def reload():
                runtime.append(target.read_text())
                if len(runtime) == 1:
                    raise RuntimeError("nginx reload failed")
            with self.assertRaises(RuntimeError):
                routes.update_routes(self.destinations(), target, lambda: None, reload)
            self.assertEqual(runtime[-1], "old destinations")
            self.assertEqual(len(runtime), 2)

    def test_untrusted_endpoint_or_injected_key_cannot_change_nginx_config(self):
        routes = self.module()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "destinations.conf"
            target.write_text("old destinations")
            for server, key in [("rtmp://attacker.example/basic", "valid-test-key-123"),
                                ("rtmp://in.uk.zap.stream:1935/basic", "private-key; include /tmp/evil;")]:
                payload = self.destinations()
                payload["zap"] = {"server": server, "key": key}
                with self.assertRaises(ValueError) as error:
                    routes.update_routes(payload, target, lambda: None, lambda: None)
                self.assertNotIn(key, str(error.exception))
                self.assertEqual(target.read_text(), "old destinations")

    def test_concurrent_refreshes_are_serialized_through_reload(self):
        routes = self.module()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "destinations.conf"
            target.write_text("old destinations")
            first_validating = threading.Event()
            release_first = threading.Event()
            second_validating = threading.Event()
            errors = []

            def first_validate():
                first_validating.set()
                if not release_first.wait(3):
                    raise RuntimeError("test synchronization timed out")

            def run(payload, validate):
                try:
                    routes.update_routes(payload, target, validate, lambda: None)
                except Exception as error:
                    errors.append(error)

            first = threading.Thread(target=run, args=(self.destinations(), first_validate))
            second_payload = self.destinations()
            second_payload["zap"]["key"] = "new-zap-test-key-123"
            second = threading.Thread(target=run, args=(second_payload, second_validating.set))
            first.start()
            self.assertTrue(first_validating.wait(2))
            second.start()
            premature = second_validating.wait(0.2)
            release_first.set()
            first.join(3)
            second.join(3)
            self.assertFalse(premature, "second update entered the transaction while the first held it")
            self.assertEqual(errors, [])
            self.assertIn("new-zap-test-key-123", target.read_text())


if __name__ == "__main__":
    unittest.main()
