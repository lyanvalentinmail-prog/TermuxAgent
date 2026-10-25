"""OpenAI-compatible chat completions client using only the Python standard library."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class AIError(RuntimeError):
    pass


class ChatClient:
    def __init__(self, config: Any):
        self.config = config

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        api_key = self.config.values.get("api_key")
        if not api_key:
            raise AIError("Falta la API key. Ejecuta `termux-agent setup` o define TERMUXAGENT_API_KEY.")
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": float(self.config.temperature),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "TermuxAgent/0.1"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:1000]
            raise AIError(f"El proveedor respondió HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AIError(f"No se pudo conectar con el proveedor: {exc}") from exc
        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(f"Respuesta inesperada del proveedor: {str(data)[:500]}") from exc
