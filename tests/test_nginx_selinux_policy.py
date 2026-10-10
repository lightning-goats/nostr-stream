import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "nginx" / "lightning_goats_rtmp.te"


class NginxSELinuxPolicyTests(unittest.TestCase):
    def test_policy_grants_only_nginx_access_to_the_managed_rtmp_port(self):
        source = POLICY.read_text()

        self.assertIn("type lightning_goats_rtmp_port_t, port_type;", source)
        self.assertIn(
            "allow httpd_t lightning_goats_rtmp_port_t:tcp_socket name_connect;",
            source,
        )
        self.assertEqual(len(re.findall(r"\ballow\s+", source)), 1)
        self.assertNotIn("httpd_can_network_connect", source)

    @unittest.skipUnless(
        shutil.which("checkmodule") and shutil.which("semodule_package"),
        "SELinux policy build tools are not installed",
    )
    def test_policy_compiles_and_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            module = Path(directory) / "lightning_goats_rtmp.mod"
            package = Path(directory) / "lightning_goats_rtmp.pp"
            subprocess.run(
                ["checkmodule", "-M", "-m", "-o", str(module), str(POLICY)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "semodule_package",
                    "-o",
                    str(package),
                    "-m",
                    str(module),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertGreater(package.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
