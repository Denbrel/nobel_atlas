"""Start Streamlit locally and verify JS/CSS bytes, MIME types and map assets.

This checks HTTP delivery, not JavaScript execution in a browser or a public tunnel.
Usage: python scripts/smoke_http.py
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from importlib import resources
from pathlib import Path
import hashlib
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def fetch(url):
    """Прочитать HTTP-статус, MIME-тип и байты с ограниченным временем ожидания."""
    request = urllib.request.Request(
        url,
        headers={"Cache-Control": "no-cache", "User-Agent": "NobelAtlas-smoke-test"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.status, response.headers.get_content_type(), response.read()


def main():
    """Запустить временный сервер и проверить выдачу JS/CSS и подложки; затем остановить его."""
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="nobel-http-") as temp:
        logpath = Path(temp) / "streamlit.log"
        with logpath.open("w") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    "app.py",
                    "--server.headless=true",
                    "--server.address=127.0.0.1",
                    f"--server.port={port}",
                ],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Streamlit exited before health check")
                    try:
                        if fetch(base + "/_stcore/health")[0] == 200:
                            break
                    except (OSError, TimeoutError):
                        pass
                    time.sleep(0.25)
                else:
                    raise RuntimeError("Streamlit health endpoint timed out")
                status, mime, html = fetch(base + "/")
                assert status == 200 and mime == "text/html", (status, mime)
                static = Path(str(resources.files("streamlit") / "static"))
                files = sorted([*static.rglob("*.js"), *static.rglob("*.css")])
                assert files, "No frontend assets in installed Streamlit distribution"

                def check(path):
                    """Сверить MIME-тип и SHA-256 одного файла с установленным дистрибутивом Streamlit."""
                    relative = path.relative_to(static).as_posix()
                    status, mime, body = fetch(base + "/" + relative)
                    expected = (
                        ("text/javascript", "application/javascript")
                        if path.suffix == ".js"
                        else ("text/css",)
                    )
                    assert (
                        status == 200 and mime in expected
                    ), f"{relative}: {status} {mime}"
                    assert (
                        hashlib.sha256(body).digest()
                        == hashlib.sha256(path.read_bytes()).digest()
                    ), relative
                    return relative

                with ThreadPoolExecutor(max_workers=6) as pool:
                    checked = list(pool.map(check, files))
                status, mime, data = fetch(base + "/app/static/world_110m.json")
                assert status == 200 and json.loads(data)["type"] == "Topology"
                print(
                    json.dumps(
                        {
                            "health": "ok",
                            "frontend_assets_verified": len(checked),
                            "button_modules": [x for x in checked if "Button." in x],
                            "map_asset": "ok",
                            "browser_javascript_execution": "not tested",
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except Exception:
                print(logpath.read_text(), file=sys.stderr)
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
