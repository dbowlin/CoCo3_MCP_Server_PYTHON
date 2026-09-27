"""Section 2 — TCP bridge server that talks to bridge.lua."""

from __future__ import annotations

import json
import socket
import threading
import time
import unittest

from coco3_mcp.bridge_server import create_bridge_server


def _once_connect(sock: socket.socket, host: str, port: int, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while True:
        try:
            sock.connect((host, port))
            return
        except OSError:
            if time.time() >= deadline:
                raise
            time.sleep(0.01)


class BridgeServerTests(unittest.TestCase):
    def test_bridge_listens_and_correlates_response_ids(self) -> None:
        bridge = create_bridge_server(0)
        client: socket.socket | None = None
        try:
            bridge.start()
            self.assertEqual(bridge.address, "127.0.0.1")
            self.assertTrue(bridge.listening)
            self.assertGreater(bridge.port, 0)

            client = socket.create_connection(("127.0.0.1", bridge.port), timeout=5)
            bridge.wait_until_connected()
            buf = b""
            seen: list[dict] = []
            done = threading.Event()

            def reader() -> None:
                nonlocal buf
                while not done.is_set():
                    try:
                        chunk = client.recv(4096)
                    except OSError:
                        return
                    if not chunk:
                        return
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        req = json.loads(line.decode("utf-8"))
                        seen.append(req)
                        if len(seen) == 2:
                            first, second = seen
                            client.sendall(
                                (json.dumps({"id": second["id"], "ok": True, "result": {"cmd": second["cmd"]}}) + "\n").encode()
                            )
                            client.sendall(
                                (json.dumps({"id": first["id"], "ok": True, "result": {"cmd": first["cmd"]}}) + "\n").encode()
                            )

            thread = threading.Thread(target=reader, daemon=True)
            thread.start()

            # Fire both requests concurrently (same as the original Promise.all test).
            results: dict[str, dict] = {}
            errors: list[BaseException] = []

            def do_ping() -> None:
                try:
                    results["left"] = bridge.request("ping", {})
                except BaseException as exc:  # noqa: BLE001 — collect for assertion
                    errors.append(exc)

            def do_status() -> None:
                try:
                    results["right"] = bridge.request("status", {})
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            t1 = threading.Thread(target=do_ping)
            t2 = threading.Thread(target=do_status)
            t1.start()
            t2.start()
            t1.join(timeout=10)
            t2.join(timeout=10)
            self.assertEqual(errors, [])
            left = results["left"]
            right = results["right"]
            self.assertEqual(left["id"], "1")
            self.assertEqual(right["id"], "2")
            self.assertTrue(left["ok"])
            self.assertTrue(right["ok"])
            self.assertEqual(left["result"], {"cmd": "ping"})
            self.assertEqual(right["result"], {"cmd": "status"})
            done.set()
        finally:
            if client is not None:
                client.close()
            bridge.stop()

    def test_request_without_client_reports_not_connected(self) -> None:
        bridge = create_bridge_server(0)
        try:
            bridge.start()
            with self.assertRaisesRegex(RuntimeError, "bridge not connected"):
                bridge.request("status", {})
        finally:
            bridge.stop()

    def test_malformed_line_reaches_on_protocol_error(self) -> None:
        seen: list[tuple[str, BaseException]] = []

        def on_error(line: str, error: BaseException) -> None:
            seen.append((line, error))

        bridge = create_bridge_server(0, on_error)
        client: socket.socket | None = None
        try:
            bridge.start()
            client = socket.create_connection(("127.0.0.1", bridge.port), timeout=5)
            bridge.wait_until_connected()
            buf = b""
            stop = threading.Event()

            def reader() -> None:
                nonlocal buf
                while not stop.is_set():
                    try:
                        chunk = client.recv(4096)
                    except OSError:
                        return
                    if not chunk:
                        return
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        req = json.loads(line.decode("utf-8"))
                        client.sendall(b"not json at all\n")
                        client.sendall(
                            (json.dumps({"id": req["id"], "ok": True, "result": {}}) + "\n").encode()
                        )

            thread = threading.Thread(target=reader, daemon=True)
            thread.start()
            response = bridge.request("ping", {})
            self.assertTrue(response["ok"])
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0][0], "not json at all")
            self.assertIsInstance(seen[0][1], Exception)
            stop.set()
        finally:
            if client is not None:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                client.close()
            bridge.stop()

    def test_request_times_out_when_client_stays_silent(self) -> None:
        bridge = create_bridge_server(0)
        client: socket.socket | None = None
        try:
            bridge.start()
            client = socket.create_connection(("127.0.0.1", bridge.port), timeout=5)
            bridge.wait_until_connected()
            stop = threading.Event()

            def reader() -> None:
                while not stop.is_set():
                    try:
                        chunk = client.recv(4096)
                    except OSError:
                        return
                    if not chunk:
                        return

            thread = threading.Thread(target=reader, daemon=True)
            thread.start()
            with self.assertRaisesRegex(TimeoutError, "ping"):
                bridge.request("ping", {}, timeout_ms=200)
            stop.set()
        finally:
            if client is not None:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                client.close()
            bridge.stop()


if __name__ == "__main__":
    unittest.main()
