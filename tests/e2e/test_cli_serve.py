"""M3: `carma serve` in its own process answers over HTTP, the way a user runs it."""

import subprocess
import sys
import time

import httpx2
import pytest

pytestmark = pytest.mark.e2e


def test_serve_answers_over_http(golden_project, free_port):
    base = f"http://127.0.0.1:{free_port}"
    process = subprocess.Popen(
        [sys.executable, "-m", "carma.cli", "serve", "--project", str(golden_project), "--port", str(free_port)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        status = None
        deadline = time.monotonic() + 30
        while status is None and time.monotonic() < deadline and process.poll() is None:
            try:
                status = httpx2.get(f"{base}/api/v0/status", timeout=1).json()
            except httpx2.TransportError:
                time.sleep(0.2)
        assert status is not None, process.stdout.read() if process.poll() is not None else "no answer in 30 s"
        assert status["components"] == 6 and status["contracts"]["api"] == "api/0.1"
        view = httpx2.get(f"{base}/api/v0/view", params={"scope": "render"}).json()
        assert [n["id"] for n in view["nodes"]] == ["render.backend", "render._self"]
        assert httpx2.get(base).status_code == 200  # the map, or the page that says how to build it
    finally:
        process.terminate()
        process.wait(timeout=15)
