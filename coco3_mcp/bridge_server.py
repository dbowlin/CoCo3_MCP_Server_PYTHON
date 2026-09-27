"""TCP server that accepts one Lua bridge.lua connection and correlates JSON replies."""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from coco3_mcp.protocol import encode_request, parse_response_line

OnProtocolError = Callable[[str, BaseException], None]


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    response: dict[str, Any] | None = None
    error: BaseException | None = None


class BridgeClient:
    def __init__(self, port: int, on_protocol_error: OnProtocolError | None = None) -> None:
        self._wanted_port = port
        self._on_protocol_error = on_protocol_error
        self._server: socket.socket | None = None
        self._client: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._reader_thread: threading.Thread | None = None
        self._buffer = ""
        self._next_id = 1
        self._bound_port = port
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.Lock()
        self._listening = False
        self._stop = threading.Event()

    @property
    def listening(self) -> bool:
        return self._listening

    @property
    def port(self) -> int:
        return self._bound_port

    @property
    def address(self) -> str:
        return "127.0.0.1"

    @property
    def connected(self) -> bool:
        return self._client is not None

    def wait_until_connected(self, timeout_s: float = 5.0) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self._client is not None:
                return
            time.sleep(0.01)
        raise TimeoutError("bridge client did not connect")

    def start(self) -> None:
        with self._lock:
            if self._server is not None:
                return
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", self._wanted_port))
            server.listen(1)
            server.settimeout(0.05)
            self._server = server
            self._bound_port = server.getsockname()[1]
            self._listening = True
            self._stop.clear()
            self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
            self._accept_thread.start()

    def stop(self) -> None:
        self._fail_all(RuntimeError("bridge not connected"))
        self._stop.set()
        client = self._client
        self._client = None
        if client is not None:
            try:
                client.close()
            except OSError:
                pass
        server = self._server
        self._server = None
        self._listening = False
        if server is not None:
            try:
                server.close()
            except OSError:
                pass

    def request(self, cmd: str, params: dict[str, Any], timeout_ms: int = 5000) -> dict[str, Any]:
        with self._lock:
            client = self._client
            if client is None:
                raise RuntimeError("bridge not connected")
            req_id = str(self._next_id)
            self._next_id += 1
            line = encode_request({"id": req_id, "cmd": cmd, "params": params})
            pending = _Pending()
            self._pending[req_id] = pending
            try:
                client.sendall(line.encode("utf-8"))
            except OSError as exc:
                self._pending.pop(req_id, None)
                raise RuntimeError("bridge not connected") from exc

        if not pending.event.wait(timeout_ms / 1000.0):
            with self._lock:
                self._pending.pop(req_id, None)
            raise TimeoutError(f"timeout waiting for {cmd}")
        if pending.error is not None:
            raise pending.error
        assert pending.response is not None
        return pending.response

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            server = self._server
            if server is None:
                return
            try:
                conn, _addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self._lock:
                old = self._client
                self._client = conn
                self._buffer = ""
            if old is not None:
                try:
                    old.close()
                except OSError:
                    pass
            self._reader_thread = threading.Thread(
                target=self._reader_loop, args=(conn,), daemon=True
            )
            self._reader_thread.start()

    def _reader_loop(self, conn: socket.socket) -> None:
        try:
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    break
                if not chunk:
                    break
                self._on_data(chunk.decode("utf-8", errors="replace"))
        finally:
            with self._lock:
                if self._client is conn:
                    self._client = None
            self._fail_all(RuntimeError("bridge not connected"))

    def _on_data(self, chunk: str) -> None:
        self._buffer += chunk
        while True:
            newline = self._buffer.find("\n")
            if newline < 0:
                break
            line = self._buffer[:newline]
            self._buffer = self._buffer[newline + 1 :]
            try:
                message = parse_response_line(line)
            except ValueError as exc:
                if self._on_protocol_error is not None:
                    self._on_protocol_error(line, exc)
                continue
            with self._lock:
                entry = self._pending.pop(message["id"], None)
            if entry is not None:
                entry.response = message
                entry.event.set()

    def _fail_all(self, error: BaseException) -> None:
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for entry in pending:
            entry.error = error
            entry.event.set()


def create_bridge_server(
    port: int, on_protocol_error: OnProtocolError | None = None
) -> BridgeClient:
    return BridgeClient(port, on_protocol_error)
