"""Small dependency-free Chrome DevTools helpers for repository browser gates."""

from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO


class BrowserVerificationError(RuntimeError):
    """Raised when a local Chrome verification cannot continue."""


@dataclass
class BrowserResult:
    """Collect browser errors independently from product assertions."""

    console_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    bad_responses: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.console_errors and not self.page_errors and not self.bad_responses


class WebSocket:
    """Minimal RFC 6455 client for local Chrome DevTools traffic."""

    def __init__(self, url: str, timeout: float = 10.0) -> None:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme != "ws":
            raise BrowserVerificationError(f"Unsupported DevTools websocket scheme: {parsed.scheme}")
        self.sock = socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 80), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parsed.netloc}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = self._read_http_headers()
        if " 101 " not in response.split("\r\n", 1)[0]:
            raise BrowserVerificationError(f"Chrome websocket handshake failed: {response.splitlines()[0]}")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def send_json(self, payload: dict[str, Any]) -> None:
        self._send_frame(json.dumps(payload, separators=(",", ":")).encode("utf-8"), opcode=0x1)

    def recv_json(self, timeout: float | None = None) -> dict[str, Any] | None:
        previous_timeout = self.sock.gettimeout()
        if timeout is not None:
            self.sock.settimeout(timeout)
        try:
            while True:
                opcode, payload = self._recv_frame()
                if opcode == 0x1:
                    return json.loads(payload.decode("utf-8"))
                if opcode == 0x8:
                    return None
                if opcode == 0x9:
                    self._send_frame(payload, opcode=0xA)
        except TimeoutError:
            return None
        finally:
            self.sock.settimeout(previous_timeout)

    def _read_http_headers(self) -> str:
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            response += chunk
        return response.decode("iso-8859-1", errors="replace")

    def _send_frame(self, payload: bytes, *, opcode: int) -> None:
        first = 0x80 | opcode
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", first, 0x80 | length)
        elif length < 65536:
            header = struct.pack("!BBH", first, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", first, 0x80 | 127, length)
        mask = secrets.token_bytes(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def _recv_frame(self) -> tuple[int, bytes]:
        first, second = self._recv_exact(2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if second & 0x80 else b""
        payload = self._recv_exact(length) if length else b""
        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def _recv_exact(self, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise BrowserVerificationError("Chrome DevTools websocket closed unexpectedly")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


class CDPClient:
    """Chrome DevTools client with console, page and network error collection."""

    def __init__(self, websocket_url: str, result: BrowserResult) -> None:
        self.ws = WebSocket(websocket_url)
        self.result = result
        self.next_id = 1
        self.load_seen = False
        self.request_methods: dict[str, str] = {}

    def close(self) -> None:
        self.ws.close()

    def command(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 10.0) -> dict[str, Any]:
        message_id = self.next_id
        self.next_id += 1
        self.ws.send_json({"id": message_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.ws.recv_json(timeout=max(0.05, deadline - time.monotonic()))
            if message is None:
                continue
            if "method" in message:
                self._handle_event(message)
                continue
            if message.get("id") == message_id:
                if "error" in message:
                    raise BrowserVerificationError(f"CDP command {method} failed: {message['error']}")
                return message.get("result", {})
        raise BrowserVerificationError(f"Timed out waiting for CDP command: {method}")

    def evaluate(self, expression: str, *, timeout: float = 10.0) -> Any:
        response = self.command(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True, "userGesture": True},
            timeout=timeout,
        )
        if "exceptionDetails" in response:
            details = response["exceptionDetails"]
            message = details.get("exception", {}).get("description") or details.get("text") or "Runtime.evaluate failed"
            raise BrowserVerificationError(str(message))
        return response.get("result", {}).get("value")

    def wait_for_load(self, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while not self.load_seen and time.monotonic() < deadline:
            message = self.ws.recv_json(timeout=max(0.05, deadline - time.monotonic()))
            if message and "method" in message:
                self._handle_event(message)
        if not self.load_seen:
            raise BrowserVerificationError("Timed out waiting for page load")

    def pump(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            message = self.ws.recv_json(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
            if message and "method" in message:
                self._handle_event(message)

    def _handle_event(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params", {})
        if method == "Page.loadEventFired":
            self.load_seen = True
        elif method == "Runtime.consoleAPICalled" and params.get("type") == "error":
            values = [str(arg.get("value") or arg.get("description") or "") for arg in params.get("args", [])]
            self.result.console_errors.append(" ".join(value for value in values if value))
        elif method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails", {})
            exception = details.get("exception", {})
            self.result.page_errors.append(str(exception.get("description") or exception.get("value") or details.get("text") or "Uncaught"))
        elif method == "Log.entryAdded" and params.get("entry", {}).get("level") == "error":
            self.result.console_errors.append(str(params["entry"].get("text") or "Chrome log error"))
        elif method == "Network.requestWillBeSent":
            self.request_methods[str(params.get("requestId", ""))] = str(params.get("request", {}).get("method", "GET"))
        elif method == "Network.responseReceived":
            response = params.get("response", {})
            status = int(response.get("status", 0) or 0)
            url = str(response.get("url", ""))
            request_id = str(params.get("requestId", ""))
            if status >= 400 and not url.startswith("data:"):
                self.result.bad_responses.append({"method": self.request_methods.get(request_id, "GET"), "status": status, "url": url})
        elif method == "Network.loadingFailed" and not params.get("canceled"):
            error = str(params.get("errorText", ""))
            if error and error != "net::ERR_ABORTED":
                self.result.bad_responses.append({"error": error, "requestId": params.get("requestId")})


class ChromePage:
    """Context manager for an isolated local headless Chrome page."""

    def __init__(self, result: BrowserResult) -> None:
        self.result = result
        self.port = find_free_port()
        self.profile = tempfile.mkdtemp(prefix="oldman-browser-")
        self.process: subprocess.Popen[bytes] | None = None
        self.client: CDPClient | None = None
        self.stderr: BinaryIO | None = None

    def __enter__(self) -> CDPClient:
        self.stderr = tempfile.TemporaryFile(mode="w+b")
        try:
            self.process = launch_chrome(self.port, self.profile, stderr=self.stderr)
            wait_for_chrome(self.process, self.port)
            self.client = CDPClient(create_page_websocket(self.port), self.result)
            for domain in ("Page", "Runtime", "Network", "Log"):
                self.client.command(f"{domain}.enable")
            return self.client
        except BaseException as exc:
            self._stop_process()
            stderr = self._read_stderr()
            self._close_stderr()
            shutil.rmtree(self.profile, ignore_errors=True)
            if stderr and isinstance(exc, BrowserVerificationError):
                raise BrowserVerificationError(f"{exc}\nChrome stderr:\n{stderr}") from exc
            raise

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        if self.client is not None:
            self.client.close()
        self._stop_process()
        self._close_stderr()
        shutil.rmtree(self.profile, ignore_errors=True)

    def _stop_process(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def _read_stderr(self, limit: int = 32 * 1024) -> str:
        if self.stderr is None or self.stderr.closed:
            return ""
        self.stderr.flush()
        size = self.stderr.seek(0, os.SEEK_END)
        self.stderr.seek(max(0, size - limit))
        return self.stderr.read().decode("utf-8", errors="replace").strip()

    def _close_stderr(self) -> None:
        if self.stderr is not None:
            self.stderr.close()
            self.stderr = None


def find_chrome() -> str:
    """Return an installed Chrome/Chromium executable."""
    for candidate in (
        os.environ.get("CHROME_BIN"),
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
    ):
        if candidate and (resolved := shutil.which(candidate)):
            return resolved
    raise BrowserVerificationError("No Chrome/Chromium executable found; install Chrome or set CHROME_BIN")


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def launch_chrome(port: int, profile: str, *, stderr: int | BinaryIO = subprocess.DEVNULL) -> subprocess.Popen[bytes]:
    args = [
        find_chrome(),
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-extensions",
        "--disable-gpu",
        "--disable-sync",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "about:blank",
    ]
    if os.environ.get("OLDMAN_CHROME_HEADLESS", "1") != "0":
        args.insert(1, "--headless=new")
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=stderr)


def wait_for_chrome(process: subprocess.Popen[bytes], port: int, timeout: float = 25.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise BrowserVerificationError(f"Chrome exited before DevTools became available: {process.returncode}")
        try:
            devtools_json(port, "/json/version")
            return
        except (OSError, BrowserVerificationError, json.JSONDecodeError):
            time.sleep(0.1)
    raise BrowserVerificationError("Timed out waiting for Chrome DevTools")


def devtools_json(port: int, path: str, *, method: str = "GET") -> dict[str, Any]:
    with socket.create_connection(("127.0.0.1", port), timeout=2.0) as sock:
        request = f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
        sock.sendall(request.encode("ascii"))
        response = _read_http_response(sock)
    status = response.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    if " 200 " not in status:
        raise BrowserVerificationError(f"Chrome DevTools HTTP request failed: {status}")
    return json.loads(response.split(b"\r\n\r\n", 1)[1].decode("utf-8"))


def create_page_websocket(port: int) -> str:
    target = devtools_json(port, "/json/new?about:blank", method="PUT")
    websocket_url = target.get("webSocketDebuggerUrl")
    if not websocket_url:
        raise BrowserVerificationError("Chrome did not return a page websocket URL")
    return str(websocket_url)


def _read_http_response(sock: socket.socket) -> bytes:
    response = b""
    while b"\r\n\r\n" not in response:
        response += sock.recv(4096)
    headers, body = response.split(b"\r\n\r\n", 1)
    length = 0
    for line in headers.split(b"\r\n"):
        name, _, value = line.partition(b":")
        if name.lower() == b"content-length":
            length = int(value.strip())
            break
    while length and len(body) < length:
        body += sock.recv(length - len(body))
    return headers + b"\r\n\r\n" + body


def configure_viewport(client: CDPClient, width: int, height: int, *, mobile: bool) -> None:
    client.command(
        "Emulation.setDeviceMetricsOverride",
        {"width": width, "height": height, "deviceScaleFactor": 2 if mobile else 1, "mobile": mobile},
    )
    client.command("Emulation.setVisibleSize", {"width": width, "height": height})


def navigate(client: CDPClient, url: str) -> None:
    client.load_seen = False
    client.command("Page.navigate", {"url": url})
    try:
        client.wait_for_load(timeout=8.0)
    except BrowserVerificationError:
        if client.evaluate("document.readyState", timeout=5.0) != "complete":
            raise
    client.evaluate(
        "new Promise(resolve => { if (document.readyState === 'complete') resolve(true); else window.addEventListener('load', () => resolve(true), { once: true }); })",
        timeout=5.0,
    )
    client.pump(0.25)


def clear_origin(client: CDPClient, origin: str) -> None:
    client.command("Network.clearBrowserCookies")
    client.command("Network.clearBrowserCache")
    client.command("Storage.clearDataForOrigin", {"origin": origin.rstrip("/"), "storageTypes": "all"})


def capture_screenshot(client: CDPClient, *, capture_beyond_viewport: bool = True) -> bytes:
    """Capture a PNG from the current page."""
    data = client.command(
        "Page.captureScreenshot",
        {"format": "png", "captureBeyondViewport": capture_beyond_viewport},
        timeout=10.0,
    ).get("data")
    if not data:
        raise BrowserVerificationError("Chrome returned no screenshot data")
    return base64.b64decode(str(data))


def save_screenshot(client: CDPClient, path: str, *, capture_beyond_viewport: bool = True) -> bytes:
    """Capture a PNG, write the artifact, and return the encoded bytes."""
    data = capture_screenshot(client, capture_beyond_viewport=capture_beyond_viewport)
    Path(path).write_bytes(data)
    return data


__all__ = [
    "BrowserResult",
    "BrowserVerificationError",
    "CDPClient",
    "ChromePage",
    "capture_screenshot",
    "clear_origin",
    "configure_viewport",
    "navigate",
    "save_screenshot",
]
