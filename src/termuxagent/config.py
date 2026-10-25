"""Configuration loading and secure on-device persistence."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

APP_DIR = Path(os.environ.get("TERMUXAGENT_HOME", Path.home() / ".termuxagent"))
CONFIG_FILE = APP_DIR / "config.json"

DEFAULTS: dict[str, Any] = {
    "base_url": "https://openrouter.ai/api/v1",
    "model": "openai/gpt-4o-mini",
    "image_model": "openai/gpt-image-1",
    "video_model": "",
    "mode": "agent",
    "temperature": 0.7,
    "max_steps": 8,
    "workspace": str(Path.home()),
    "connectors": ["files", "shell", "web", "github", "android", "telegram", "discord", "image", "video"],
}

@dataclass
class Config:
    values: dict[str, Any] = field(default_factory=lambda: DEFAULTS.copy())

    @classmethod
    def load(cls) -> "Config":
        values = DEFAULTS.copy()
        try:
            if CONFIG_FILE.exists():
                saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    values.update(saved)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"No se pudo leer {CONFIG_FILE}: {exc}") from exc
        # Environment variables take precedence, so secrets need not be stored in the file.
        env_map = {
            "TERMUXAGENT_API_KEY": "api_key",
            "OPENAI_API_KEY": "api_key",
            "TERMUXAGENT_BASE_URL": "base_url",
            "TERMUXAGENT_MODEL": "model",
            "TERMUXAGENT_IMAGE_MODEL": "image_model",
            "TERMUXAGENT_VIDEO_MODEL": "video_model",
            "TERMUXAGENT_REPLICATE_TOKEN": "replicate_token",
            "TERMUXAGENT_TAVILY_KEY": "tavily_key",
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
