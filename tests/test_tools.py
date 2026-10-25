import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from termuxagent import config as config_module
from termuxagent.config import Config
from termuxagent.llm import AIError, _local_endpoint
from termuxagent.tools import ToolRegistry, _local_service_url


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

    def test_cloud_ai_endpoint_is_rejected(self):
        with self.assertRaises(AIError):
            _local_endpoint("https://api.example.com/v1")
        self.assertEqual(_local_endpoint("http://127.0.0.1:8080/v1"), "http://127.0.0.1:8080/v1")

    def test_comfyui_remote_endpoint_is_rejected(self):
        with self.assertRaises(ValueError):
            _local_service_url("https://comfy.example.com")
        self.assertEqual(_local_service_url("http://localhost:8188/"), "http://localhost:8188")

    def test_legacy_cloud_configuration_is_migrated_and_scrubbed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"base_url":"https://api.openai.com/v1","model":"remote-model","api_key":"old-secret"}')
            with patch.object(config_module, "CONFIG_FILE", path), patch.object(config_module, "APP_DIR", Path(tmp)):
                config = Config.load()
            self.assertEqual(config.base_url, "http://127.0.0.1:8080/v1")
            self.assertNotIn("api_key", config.values)
            saved = path.read_text()
            self.assertNotIn("old-secret", saved)
            self.assertNotIn("openai.com", saved)

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
