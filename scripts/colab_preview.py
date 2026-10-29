"""Managed temporary preview for Colab; no localtunnel and no IP password.

Creates a public temporary URL only when PreviewRuntime.start() is called.
Only terminates processes that this object started.
"""

from pathlib import Path
from urllib.request import urlopen
import hashlib
import platform
import re
import shutil
import socket
import subprocess
import sys
import time

CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/download/2026.10.5/cloudflared-linux-amd64"
CLOUDFLARED_SHA256 = "e1bc0cf084fd9e590554fe769a86b1db46701c3f847a43d902f7b974a4e16298"
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com\b")


def download_cloudflared(folder):
    """Скачать закреплённый официальный бинарный файл и проверить SHA-256 до запуска."""
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise RuntimeError("This helper targets Colab Linux x86_64.")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    binary = folder / "cloudflared"
    if (
        binary.exists()
        and hashlib.sha256(binary.read_bytes()).hexdigest() == CLOUDFLARED_SHA256
    ):
        return binary
    staging = binary.with_suffix(".download")
    try:
        with urlopen(CLOUDFLARED_URL, timeout=60) as response, staging.open(
            "wb"
        ) as output:
            shutil.copyfileobj(response, output)
        if hashlib.sha256(staging.read_bytes()).hexdigest() != CLOUDFLARED_SHA256:
            raise RuntimeError(
                "cloudflared checksum mismatch; download was not executed"
            )
        staging.chmod(0o700)
        staging.replace(binary)
    finally:
        staging.unlink(missing_ok=True)
    return binary


def healthy(url):
    """Проверить HTTP health endpoint с конечным таймаутом."""
    try:
        with urlopen(url.rstrip("/") + "/_stcore/health", timeout=5) as response:
            return response.status == 200 and response.read().strip().lower() == b"ok"
    except (OSError, TimeoutError):
        return False


class PreviewRuntime:
    """Управляет только собственными процессами сервера и временного туннеля."""

    def __init__(self, root, python=None):
        """Сохранить пути интерпретатора, проекта и диагностических журналов."""
        self.root = Path(root).resolve()
        self.python = str(python or sys.executable)
        self.folder = self.root / ".preview-runtime"
        self.folder.mkdir(exist_ok=True)
        self.server = None
        self.tunnel = None
        self.url = None

    def _spawn(self, command, log_name):
        """Запустить процесс в корне проекта, направив вывод в отдельный журнал."""
        with (self.folder / log_name).open("w") as log:
            return subprocess.Popen(
                command, cwd=self.root, stdout=log, stderr=subprocess.STDOUT
            )

    def stop(self):
        """Остановить только созданные этим объектом процессы и очистить их ссылки."""
        for process in (self.tunnel, self.server):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        self.tunnel = self.server = None
        self.url = None

    def start(self):
        """Выбрать свободный порт, дождаться сервера и вернуть временную публичную ссылку."""
        self.stop()
        binary = download_cloudflared(self.folder)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        local = f"http://127.0.0.1:{port}"
        try:
            self.server = self._spawn(
                [
                    self.python,
                    "-m",
                    "streamlit",
                    "run",
                    "app.py",
                    "--server.headless=true",
                    "--server.address=127.0.0.1",
                    f"--server.port={port}",
                ],
                "streamlit.log",
            )
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if self.server.poll() is not None:
                    raise RuntimeError(
                        "Streamlit stopped; see .preview-runtime/streamlit.log"
                    )
                if healthy(local):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("Streamlit did not become healthy; see its log")
            self.tunnel = self._spawn(
                [
                    str(binary),
                    "tunnel",
                    "--no-autoupdate",
                    "--protocol",
                    "http2",
                    "--url",
                    local,
                ],
                "tunnel.log",
            )
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if self.tunnel.poll() is not None:
                    raise RuntimeError(
                        "Tunnel stopped; see .preview-runtime/tunnel.log"
                    )
                log = (self.folder / "tunnel.log").read_text(errors="replace")
                match = TUNNEL_URL.search(log)
                if match:
                    self.url = match.group(0)
                    if healthy(self.url):
                        return self.url
                time.sleep(1)
            raise RuntimeError(
                "Temporary tunnel unavailable; see .preview-runtime/tunnel.log"
            )
        except Exception:
            self.stop()
            raise
