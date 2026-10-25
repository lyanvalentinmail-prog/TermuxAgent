import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from termuxagent.tools import ToolRegistry


class ToolRegistryTests(unittest.TestCase):
    def make_registry(self, enabled=None, confirm=None):
        root = tempfile.mkdtemp()
        config = SimpleNamespace(
            workspace=root,
            connectors=enabled or ["files", "shell", "web", "github", "android", "telegram", "discord", "image", "video"],
            values={"api_key": "", "tavily_key": "", "github_token": ""},
            image_model="test-image",
            base_url="https://example.invalid/v1",
        )
        return ToolRegistry(config, confirm or (lambda _: False)), Path(root)

    def test_tools_are_filtered_by_connector(self):
        registry, _ = self.make_registry(["files"])
        self.assertIn("read_file", registry.tools)
        self.assertIn("current_time", registry.tools)
        self.assertNotIn("run_command", registry.tools)
        self.assertNotIn("generate_video", registry.tools)

    def test_provider_schemas_do_not_expose_internal_connector_metadata(self):
        registry, _ = self.make_registry()
        schemas = registry.definitions()
        self.assertTrue(schemas)
        self.assertTrue(all("connector" not in schema["function"] for schema in schemas))

    def test_path_traversal_is_rejected(self):
        registry, _ = self.make_registry(["files"])
        with self.assertRaises(ValueError):
            registry._path("../outside.txt")

    def test_write_is_cancelled_without_user_approval(self):
        registry, root = self.make_registry(["files"], lambda _: False)
        result = registry.execute("write_file", {"path": "note.txt", "content": "hello"})
        self.assertIn("cancelada", result)
        self.assertFalse((root / "note.txt").exists())

    def test_unknown_tool_is_reported(self):
        registry, _ = self.make_registry(["files"])
        self.assertIn("no disponible", registry.execute("delete_everything", {}))


if __name__ == "__main__":
    unittest.main()
