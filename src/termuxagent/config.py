"""Configuration loading and secure on-device persistence."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

APP_DIR = Path(os.environ.get("TERMUXAGENT_HOME", Path.home() / ".termuxagent"))
CONFIG_FILE = APP_DIR / "config.json"

DEFAULTS: dict[str, Any] = {
    "base_url": "http://127.0.0.1:8080/v1",
    "model": "local-model",
    "comfyui_url": "http://127.0.0.1:8188",
    "image_workflow": "",
    "video_workflow": "",
    "image_prompt_node": "",
    "video_prompt_node": "",
    "mode": "agent",
    "temperature": 0.7,
    "max_steps": 8,
    "workspace": str(Path.home()),
    "connectors": ["files", "shell", "web", "github", "android", "telegram", "discord", "image", "video"],
}

LEGACY_CLOUD_KEYS = ("api_key", "replicate_token", "tavily_key", "image_model", "video_model")


@dataclass
class Config:
    values: dict[str, Any] = field(default_factory=lambda: DEFAULTS.copy())

    @classmethod
    def load(cls) -> "Config":
        values = DEFAULTS.copy()
        saved: dict[str, Any] = {}
        try:
            if CONFIG_FILE.exists():
                loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    saved = loaded
                    values.update(saved)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"No se pudo leer {CONFIG_FILE}: {exc}") from exc

        # Remove old provider credentials from disk and memory. They are never used by this local-only build.
        migrated = any(key in saved for key in LEGACY_CLOUD_KEYS)
        for key in LEGACY_CLOUD_KEYS:
            values.pop(key, None)
            saved.pop(key, None)

        # Migrate old cloud endpoints to loopback so an upgrade cannot contact them.
        parsed = urlparse(str(values.get("base_url", "")))
        if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            values["base_url"] = DEFAULTS["base_url"]
            values["model"] = DEFAULTS["model"]
            if saved:
                saved["base_url"] = DEFAULTS["base_url"]
                saved["model"] = DEFAULTS["model"]
            migrated = True

        if migrated and CONFIG_FILE.exists():
            CONFIG_FILE.write_text(json.dumps(saved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            try:
                CONFIG_FILE.chmod(0o600)
            except OSError:
                pass

        # Inference endpoints supplied by the environment remain subject to the same loopback guard.
        env_map = {
            "TERMUXAGENT_LOCAL_URL": "base_url",
            "TERMUXAGENT_LOCAL_MODEL": "model",
            "TERMUXAGENT_COMFYUI_URL": "comfyui_url",
            "GITHUB_TOKEN": "github_token",
            "TERMUXAGENT_TELEGRAM_BOT_TOKEN": "telegram_bot_token",
            "TERMUXAGENT_TELEGRAM_CHAT_ID": "telegram_chat_id",
            "TERMUXAGENT_DISCORD_WEBHOOK": "discord_webhook",
        }
        for env_name, key in env_map.items():
            if os.getenv(env_name):
                values[key] = os.environ[env_name]
        return cls(values)

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self.values, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            CONFIG_FILE.chmod(0o600)
        except OSError:
            pass

    def __getattr__(self, name: str) -> Any:
        try:
            return self.values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc
