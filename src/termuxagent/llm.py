"""Loopback-only OpenAI-compatible client for local llama.cpp/Ollama servers."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class AIError(RuntimeError):
    pass


def _local_endpoint(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise AIError("TermuxAgent solo se conecta a modelos de IA locales (localhost). Configura llama-server en 127.0.0.1; no se permiten proveedores de IA remotos.")
    return base_url.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


class ChatClient:
    def __init__(self, config: Any):
        self.config = config

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        # A loopback-only guard makes it impossible to silently fall back to a cloud AI API.
        url = _local_endpoint(str(self.config.base_url)) + "/chat/completions"
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
            headers={"Content-Type": "application/json", "User-Agent": "TermuxAgent/0.2-local"},
            method="POST",
        )
        try:
            # Do not allow a local inference server to redirect the request off-device.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            with opener.open(req, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:1000]
            raise AIError(f"El modelo local respondió HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AIError(f"No se pudo conectar con el modelo local en {url}: {exc}. ¿Está ejecutándose llama-server?") from exc
        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(f"Respuesta inesperada del modelo local: {str(data)[:500]}") from exc
