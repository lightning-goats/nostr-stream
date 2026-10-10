import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import unittest
import io

class RelayTests(unittest.TestCase):
    def module(self):
        loader = SourceFileLoader("zap_relay", str(Path(__file__).resolve().parents[1] / "bin/lightning-goats-zap-relay"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_ffmpeg_arguments_cannot_contain_the_private_destination(self):
        module = self.module()
        args = module.ffmpeg_arguments()
        self.assertEqual(args[-1], "pipe:1")
        self.assertFalse(any("zap.stream" in arg for arg in args))

    def test_complete_flv_packets_survive_fragmented_reads(self):
        module = self.module()
        header = b"FLV\x01\x05\x00\x00\x00\x09" + b"\x00" * 4
        packet = b"\x09\x00\x00\x03" + b"\x00" * 7 + b"abc" + (14).to_bytes(4, "big")
        class Fragmented(io.BytesIO):
            def read(self, size=-1):
                return super().read(min(size, 2))
        self.assertEqual(list(module.flv_packets(Fragmented(header + packet + packet))),
                         [header + packet, packet])
        with self.assertRaises(ValueError):
            list(module.flv_packets(io.BytesIO(header + packet[:-1])))

    def test_only_validated_zap_destination_is_read_from_private_routes(self):
        module = self.module()
        url = "rtmp://in.uk.zap.stream:1935/basic/disposable-test-key-123"
        self.assertEqual(module.destination("push rtmp://a.rtmp.youtube.com/live2/test;\n# zap-relay " + url + "\n"), url)
        for invalid in ["# zap-relay rtmp://attacker.example/basic/disposable-test-key-123",
                        "# zap-relay " + url + "; injected", "",
                        "# zap-relay " + url + "\n# zap-relay " + url]:
            with self.assertRaises(ValueError):
                module.destination(invalid)

if __name__ == "__main__":
    unittest.main()
