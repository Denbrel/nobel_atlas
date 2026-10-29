"""Автоматические проверки: готовность к размещению и Colab."""

import json
from pathlib import Path
import subprocess
import sys
from scripts.colab_preview import TUNNEL_URL, PreviewRuntime

ROOT = Path(__file__).resolve().parents[1]


def test_deployment_preflight():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_deployment.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_colab_cells_have_valid_python():
    notebook = json.loads((ROOT / "notebooks/Nobel_Atlas_Colab.ipynb").read_text())
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), "<colab>", "exec")
    assert (
        TUNNEL_URL.search(
            "Tunnel ready at https://example-preview.trycloudflare.com"
        ).group(0)
        == "https://example-preview.trycloudflare.com"
    )
    assert not TUNNEL_URL.search("https://example.com")


def test_preview_stop_only_owns_its_processes(tmp_path):
    class Process:
        def __init__(self):
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            return 0

    preview = PreviewRuntime(tmp_path)
    server, tunnel = Process(), Process()
    preview.server, preview.tunnel = server, tunnel
    preview.stop()
    assert server.terminated and tunnel.terminated
    assert preview.server is None and preview.tunnel is None
