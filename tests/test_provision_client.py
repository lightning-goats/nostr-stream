import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "provision-nostr-client"
NAK = Path("/home/goats/.local/bin/nak")
APPROVED = "5302cd2bfe2dcc76c5a9abcba74e6c5f1a07444b35c25e0cd74bac5b453fb5f6"


class ProvisionTests(unittest.TestCase):
    def module(self):
        self.assertTrue(SCRIPT.exists(), "credential provisioning script is missing")
        loader = SourceFileLoader("provision", str(SCRIPT))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_unapproved_client_does_not_replace_existing_credential(self):
        module = self.module()
        # A generated test identity is deliberately different from the allowlist.
        key = subprocess.run([str(NAK), "key", "generate"], capture_output=True,
                             text=True, check=True).stdout.strip()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "nostr-client.cred"
            destination.write_bytes(b"existing encrypted credential")
            with self.assertRaisesRegex(module.CredentialError, "approved"):
                module.provision(key, APPROVED, destination, NAK)
            self.assertEqual(destination.read_bytes(), b"existing encrypted credential")

    def test_encrypted_credential_is_written_privately(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "nostr-client.cred"
            module.save_credential(destination, b"encrypted test data")
            self.assertEqual(destination.read_bytes(), b"encrypted test data")
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_approved_client_credential_decrypts_to_the_supplied_key(self):
        module = self.module()
        key = subprocess.run([str(NAK), "key", "generate"], capture_output=True,
                             text=True, check=True).stdout.strip()
        public = subprocess.run([str(NAK), "key", "public"], input=key,
                                capture_output=True, text=True, check=True).stdout.strip()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "nostr-client.cred"
            module.provision(key, public, destination, NAK)
            plaintext = subprocess.run(
                ["systemd-creds", "decrypt", "--user", "--name=nostr-client",
                 str(destination), "-"], capture_output=True, check=True).stdout
            self.assertEqual(plaintext, key.encode())


if __name__ == "__main__":
    unittest.main()
