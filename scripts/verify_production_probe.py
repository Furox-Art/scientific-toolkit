"""Verify all opt-in authenticated startup checks using a real HTTP process.

CI-only temporary secret; no Render production token is read or printed.
"""
import os
import select
import socket
import subprocess
import sys
import time


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    port = free_port()
    env = {**os.environ, "PORT": str(port),
           "SCITOOL_STARTUP_PROBE": "1",
           "SCITOOL_MCP_BEARER_TOKEN": "ci-only-test-secret-never-use-in-production"}
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "scientific_toolkit_mcp.http_server"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    outcome = None
    pending = b""
    try:
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline and outcome is None:
            if process.poll() is not None:
                raise AssertionError(f"server exited with return code {process.returncode}")
            ready, _, _ = select.select([process.stdout], [], [], 4)
            if not ready:
                continue
            chunk = os.read(process.stdout.fileno(), 16384)
            if not chunk:
                raise AssertionError("production server stdout closed")
            pending += chunk
            while b"\\n" in pending:
                raw, pending = pending.split(b"\\n", 1)
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("PRODUCTION_MCP_PROBE "):
                    continue
                print(line)
                if " RESULT=" in line:
                    outcome = line
        assert outcome, "no finished production diagnostic was reported"
        assert "RESULT=PASS" in outcome, outcome
        assert "checks_passed=12" in outcome, outcome
        assert "checks_failed=0" in outcome, outcome
        print("PASS: real HTTP authentication and six real CLIs in a single instance")
    finally:
        process.terminate()
        try:
            process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=6)


if __name__ == "__main__":
    main()
