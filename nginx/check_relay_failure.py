#!/usr/bin/env python3
"""Exercise native RTMP push retry with an unavailable loopback destination."""

import socket
import subprocess
import tempfile
import time
from pathlib import Path


def main(module, fixture):
    port = 19454
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", port))
    except OSError:
        raise SystemExit(f"Refusing relay retry test; loopback port {port} is occupied.") from None
    finally:
        probe.close()

    with tempfile.TemporaryDirectory(prefix="goats-relay-retry-") as folder:
        root = Path(folder)
        config = root / "nginx.conf"
        error_log = root / "error.log"
        config.write_text(
            f"load_module {module};\n"
            f"worker_processes 1;\npid {root}/nginx.pid;\n"
            f"error_log {error_log} info;\n"
            "events { worker_connections 32; }\n"
            "rtmp { server { access_log off;\n"
            f"listen 127.0.0.1:{port};\n"
            "application probe { live on; record off; meta publish;\n"
            "push_reconnect 1s; push rtmp://127.0.0.1:1/probe/test; } } }\n"
        )
        server = subprocess.Popen(
            ["nginx", "-p", folder, "-c", str(config), "-g", "daemon off;"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("isolated nginx did not open the test listener")

            sender = subprocess.run(
                ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-re",
                 "-i", str(fixture), "-t", "2", "-c", "copy", "-f", "flv",
                 f"rtmp://127.0.0.1:{port}/probe/test"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=12)
            if sender.returncode:
                raise RuntimeError("local publisher did not complete the isolated test")
            time.sleep(2.2)
            if server.poll() is not None:
                raise RuntimeError("isolated nginx exited during reconnect testing")
            log = error_log.read_text(errors="replace") if error_log.exists() else ""
            if "exited on signal 11" in log or "signal 11" in log.lower():
                raise RuntimeError("nginx worker crashed during unavailable-destination retry")
            if "connect() failed" not in log and "send() failed" not in log:
                raise RuntimeError("isolated test did not exercise the unavailable push: " + log[-1000:])
            print("Unavailable RTMP destination was retried without an nginx worker crash.")
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()
    main(str(args.module.resolve()), str(args.fixture.resolve()))
