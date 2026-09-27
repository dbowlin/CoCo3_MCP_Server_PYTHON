"""Activation: find MAME/decb, write .env, merge Cursor mcp.json."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from coco3_mcp.activate import (
    activate,
    discover_tools,
    ensure_listening,
    merge_cursor_config,
    render_env,
    sibling_search_roots,
)
from coco3_mcp.endpoint import DEFAULT_PORT, endpoint_document
from coco3_mcp.__main__ import project_root
from coco3_mcp.activate import app_root


class DiscoverToolsTests(unittest.TestCase):
    def test_finds_tools_under_app_and_sibling_repo(self) -> None:
        with self._tree() as (root, sibling):
            (root / "mame" / "roms").mkdir(parents=True)
            (sibling / "decb").mkdir()
            (root / "mame" / "mame.exe").write_bytes(b"m")
            (sibling / "decb" / "decb.exe").write_bytes(b"d")
            found = discover_tools(root, [sibling])
            self.assertEqual(found["mame_path"], str((root / "mame" / "mame.exe").resolve()))
            self.assertEqual(found["decb_path"], str((sibling / "decb" / "decb.exe").resolve()))
            self.assertEqual(found["mame_rom_path"], str((root / "mame" / "roms").resolve()))

    def test_sibling_roms_used_when_local_mame_has_no_roms(self) -> None:
        with self._tree() as (root, sibling):
            (sibling / "mame" / "roms").mkdir(parents=True)
            (sibling / "mame" / "mame.exe").write_bytes(b"m")
            (sibling / "mame" / "roms" / "coco3.zip").write_bytes(b"z")
            found = discover_tools(root, [sibling])
            self.assertEqual(found["mame_path"], str((sibling / "mame" / "mame.exe").resolve()))
            self.assertEqual(
                found["mame_rom_path"],
                str((sibling / "mame" / "roms").resolve()),
            )

    def test_missing_tools_are_empty_strings(self) -> None:
        with self._tree() as (root, _sibling):
            found = discover_tools(root, [])
            self.assertEqual(found, {"mame_path": "", "mame_rom_path": "", "decb_path": ""})

    def _tree(self):
        import tempfile
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            with tempfile.TemporaryDirectory(prefix="coco-act-") as tmp:
                base = Path(tmp)
                root = base / "coco3-mcp"
                sibling = base / "CoCo3_MCP_Server"
                root.mkdir()
                sibling.mkdir()
                yield root, sibling

        return _cm()


class RenderEnvTests(unittest.TestCase):
    def test_paths_inside_the_app_are_relative(self) -> None:
        root = Path("C:/apps/coco3-mcp")
        text = render_env(
            root,
            {
                "mame_path": str(root / "mame" / "mame.exe"),
                "mame_rom_path": str(root / "mame" / "roms"),
                "decb_path": str(root / "decb" / "decb.exe"),
            },
        )
        self.assertIn("MAME_PATH=mame\\mame.exe", text.replace("/", "\\"))
        self.assertIn("BRIDGE_PORT=18765", text)
        self.assertIn("COCO_RAM=512K", text)

    def test_paths_outside_the_app_stay_absolute(self) -> None:
        root = Path("C:/apps/coco3-mcp")
        outside = Path("C:/emu/mame.exe")
        text = render_env(
            root,
            {"mame_path": str(outside), "mame_rom_path": "", "decb_path": ""},
        )
        self.assertIn(f"MAME_PATH={outside}", text)
        self.assertIn("MAME_ROMPATH=mame\\roms", text.replace("/", "\\"))
        self.assertIn("DECB_PATH=decb\\decb.exe", text.replace("/", "\\"))


class MergeCursorConfigTests(unittest.TestCase):
    def test_keeps_other_servers_and_sets_coco3(self) -> None:
        merged = merge_cursor_config(
            {"mcpServers": {"other": {"command": "node", "args": ["x.js"]}}},
            python=r"C:\Python\python.exe",
            cwd=r"C:\apps\coco3-mcp",
        )
        self.assertEqual(merged["mcpServers"]["other"]["command"], "node")
        coco = merged["mcpServers"]["coco3"]
        self.assertEqual(coco["command"], r"C:\Python\python.exe")
        self.assertEqual(coco["args"], ["-m", "coco3_mcp"])
        self.assertEqual(coco["cwd"], r"C:\apps\coco3-mcp")

    def test_starts_from_empty_config(self) -> None:
        merged = merge_cursor_config(None, python="python", cwd=".")
        self.assertEqual(list(merged["mcpServers"]), ["coco3"])


class ActivateTests(unittest.TestCase):
    def test_writes_env_and_merges_mcp_json(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="coco-act-") as tmp:
            base = Path(tmp)
            root = base / "app"
            (root / "mame" / "roms").mkdir(parents=True)
            (root / "mame" / "mame.exe").write_bytes(b"m")
            (root / "decb").mkdir()
            (root / "decb" / "decb.exe").write_bytes(b"d")
            (root / "mame" / "roms" / "coco3.zip").write_bytes(b"z")
            user_mcp = base / "user" / "mcp.json"
            user_mcp.parent.mkdir()
            user_mcp.write_text(
                json.dumps({"mcpServers": {"keepme": {"command": "echo"}}}),
                encoding="utf-8",
            )
            project_mcp = root / ".cursor" / "mcp.json"
            result = activate(
                root,
                python=r"C:\Python\python.exe",
                user_mcp=user_mcp,
                project_mcp=project_mcp,
                extra_roots=[],
            )
            env = (root / ".env").read_text(encoding="utf-8")
            self.assertIn("MAME_PATH=mame\\mame.exe", env.replace("/", "\\"))
            self.assertIn("DECB_PATH=decb\\decb.exe", env.replace("/", "\\"))
            saved = json.loads(user_mcp.read_text(encoding="utf-8"))
            self.assertEqual(saved["mcpServers"]["keepme"]["command"], "echo")
            self.assertEqual(saved["mcpServers"]["coco3"]["args"], ["-m", "coco3_mcp"])
            self.assertEqual(
                json.loads(project_mcp.read_text(encoding="utf-8"))["mcpServers"]["coco3"]["cwd"],
                str(root.resolve()),
            )
            self.assertTrue((root / "storage" / "disks").is_dir())
            self.assertEqual(result["mame_path"], str((root / "mame" / "mame.exe").resolve()))

    def test_backs_up_existing_env_and_invalid_mcp_json(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="coco-act-") as tmp:
            root = Path(tmp) / "app"
            root.mkdir()
            (root / ".env").write_text("MAME_PATH=old\n", encoding="utf-8")
            user_mcp = Path(tmp) / "mcp.json"
            user_mcp.write_text("{not json", encoding="utf-8")
            activate(
                root,
                python="python",
                user_mcp=user_mcp,
                project_mcp=None,
                extra_roots=[],
            )
            self.assertEqual((root / ".env.bak").read_text(encoding="utf-8"), "MAME_PATH=old\n")
            self.assertTrue(user_mcp.with_name("mcp.json.bak").is_file())
            self.assertIn("coco3", json.loads(user_mcp.read_text(encoding="utf-8"))["mcpServers"])

    def test_activate_publishes_http_endpoint_without_an_ide(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="coco-act-") as tmp:
            base = Path(tmp)
            root = base / "app"
            root.mkdir()
            public = base / "home" / "server.json"
            result = activate(
                root,
                python=r"C:\Python\python.exe",
                user_mcp=None,
                project_mcp=None,
                extra_roots=[],
                public_endpoint=public,
            )
            self.assertFalse((root / ".cursor").exists())
            doc = json.loads(public.read_text(encoding="utf-8"))
            self.assertEqual(doc["transport"], "http")
            self.assertEqual(doc["url"], f"http://127.0.0.1:{DEFAULT_PORT}/mcp")
            self.assertEqual(doc["listen"]["args"], ["-m", "coco3_mcp.serve"])
            self.assertNotIn("mcpServers", doc)
            local = json.loads((root / "server.json").read_text(encoding="utf-8"))
            self.assertEqual(local["url"], doc["url"])
            self.assertEqual(result["url"], doc["url"])
            env = (root / ".env").read_text(encoding="utf-8")
            self.assertIn(f"MCP_PORT={DEFAULT_PORT}", env)


class EnsureListeningTests(unittest.TestCase):
    def test_already_running_does_not_spawn(self) -> None:
        spawned: list[str] = []
        status = ensure_listening(
            "127.0.0.1",
            9,
            lambda: spawned.append("spawn"),
            probe=lambda _host, _port: True,
        )
        self.assertEqual(status, "already")
        self.assertEqual(spawned, [])

    def test_spawns_and_waits_until_probe_succeeds(self) -> None:
        calls = {"n": 0}

        def check(_host: str, _port: int) -> bool:
            calls["n"] += 1
            return calls["n"] > 1

        spawned: list[str] = []
        status = ensure_listening(
            "127.0.0.1",
            9,
            lambda: spawned.append("spawn"),
            probe=check,
            timeout_s=1,
        )
        self.assertEqual(status, "started")
        self.assertEqual(spawned, ["spawn"])


class EndpointDocumentTests(unittest.TestCase):
    def test_document_is_a_plain_http_endpoint(self) -> None:
        doc = endpoint_document(
            root=Path("C:/apps/coco3-mcp"),
            python=r"C:\Python\python.exe",
            host="127.0.0.1",
            port=18766,
        )
        self.assertEqual(doc["name"], "coco3-mcp-bridge")
        self.assertEqual(doc["transport"], "http")
        self.assertEqual(doc["url"], "http://127.0.0.1:18766/mcp")
        self.assertEqual(doc["health"], "http://127.0.0.1:18766/")
        self.assertEqual(doc["listen"]["args"], ["-m", "coco3_mcp.serve"])
        self.assertEqual(doc["listen"]["cwd"], str(Path("C:/apps/coco3-mcp")))
        self.assertNotIn("mcpServers", doc)


class AppRootTests(unittest.TestCase):
    def test_app_root_matches_server_project_root(self) -> None:
        self.assertEqual(app_root(), project_root())

    def test_sibling_search_roots_sees_named_folder(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="coco-sib-") as tmp:
            base = Path(tmp)
            root = base / "coco3-mcp"
            sibling = base / "CoCo3_MCP_Server"
            root.mkdir()
            sibling.mkdir()
            self.assertEqual(sibling_search_roots(root), [sibling.resolve()])
        with tempfile.TemporaryDirectory(prefix="coco-nosib-") as tmp:
            other = Path(tmp) / "other"
            other.mkdir()
            self.assertEqual(sibling_search_roots(other), [])


if __name__ == "__main__":
    unittest.main()
