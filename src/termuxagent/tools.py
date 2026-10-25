"""Built-in connectors exposed to the agent as OpenAI-compatible function tools."""
from __future__ import annotations

import base64
import html
import ipaddress
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required or [], "additionalProperties": False,
    }}}


def _http(url: str, *, method: str = "GET", data: dict[str, Any] | None = None,
          headers: dict[str, str] | None = None, timeout: int = 30) -> bytes:
    body = json.dumps(data).encode() if data is not None else None
    hdrs = {"User-Agent": "TermuxAgent/0.1 (+https://github.com/lyanvalentinmail-prog/TermuxAgent)"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def _public_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Solo se permiten URLs http(s) válidas.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, None)
        if not addresses:
            raise ValueError("No se pudo resolver el host.")
        for entry in addresses:
            ip = ipaddress.ip_address(entry[4][0].split("%", 1)[0])
            if not ip.is_global:
                raise ValueError("Por seguridad no se permiten direcciones locales o privadas.")
    except socket.gaierror as exc:
        raise ValueError(f"No se pudo resolver el host: {exc}") from exc
    return url


@dataclass
class Tool:
    definition: dict[str, Any]
    run: Callable[[dict[str, Any]], str]

    @property
    def name(self) -> str:
        return self.definition["function"]["name"]


class ToolRegistry:
    def __init__(self, config: Any, confirm: Callable[[str], bool]):
        self.config = config
        self.confirm = confirm
        self.root = Path(config.workspace).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.tools: dict[str, Tool] = {}
        self._register_core()
        enabled = set(config.connectors)
        self.tools = {name: tool for name, tool in self.tools.items() if tool.definition["function"].get("connector") in enabled}

    def add(self, name: str, description: str, properties: dict[str, Any], required: list[str], run: Callable[[dict[str, Any]], str], connector: str) -> None:
        definition = _schema(name, description, properties, required)
        definition["function"]["connector"] = connector
        self.tools[name] = Tool(definition, run)

    def _path(self, value: str) -> Path:
        candidate = (self.root / value).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("La ruta queda fuera del workspace permitido.")
        return candidate

    def _register_core(self) -> None:
        self.add("list_files", "Lista archivos y carpetas dentro del workspace.", {"path": {"type": "string", "description": "Ruta relativa (por defecto .)"}}, [], self._list_files, "files")
        self.add("read_file", "Lee un archivo de texto dentro del workspace.", {"path": {"type": "string"}}, ["path"], self._read_file, "files")
        self.add("write_file", "Crea o reemplaza un archivo de texto. Siempre pide confirmación.", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"], self._write_file, "files")
        self.add("run_command", "Ejecuta un comando de shell en Termux tras confirmación explícita. No usar para operaciones destructivas.", {"command": {"type": "string"}}, ["command"], self._run_command, "shell")
        self.add("web_search", "Busca información en la web (Tavily si hay clave; DuckDuckGo como alternativa).", {"query": {"type": "string"}}, ["query"], self._web_search, "web")
        self.add("fetch_url", "Obtiene el texto de una página pública http(s), sin acceder a direcciones privadas.", {"url": {"type": "string"}}, ["url"], self._fetch_url, "web")
        self.add("github_search", "Busca repositorios públicos de GitHub.", {"query": {"type": "string"}}, ["query"], self._github_search, "github")
        self.add("github_issue_search", "Busca issues y pull requests públicos en GitHub.", {"query": {"type": "string"}}, ["query"], self._github_issue_search, "github")
        self.add("telegram_send", "Envía un mensaje a Telegram usando un bot y chat configurados. Siempre pide confirmación.", {"message": {"type": "string"}}, ["message"], self._telegram_send, "telegram")
        self.add("discord_send", "Envía un mensaje a un canal de Discord mediante un webhook configurado. Siempre pide confirmación.", {"message": {"type": "string"}}, ["message"], self._discord_send, "discord")
        self.add("android_action",  "Usa utilidades opcionales de Termux: abrir URL, copiar texto, compartir texto, notificación o ubicación. Requiere Termux:API para algunas acciones.", {
            "action": {"type": "string", "enum": ["open_url", "clipboard", "share", "notify", "location"]},
            "text": {"type": "string", "description": "URL, texto, o título de notificación según acción"},
        }, ["action"], self._android_action, "android")
        self.add("generate_image", "Genera una imagen con el proveedor OpenAI-compatible configurado y la guarda en el workspace.", {
            "prompt": {"type": "string"}, "filename": {"type": "string", "description": "Nombre .png/.jpg opcional"},
        }, ["prompt"], self._generate_image, "image")
        self.add("generate_video", "Genera un video con Replicate (requiere TERMUXAGENT_REPLICATE_TOKEN y video_model configurado). Puede tardar varios minutos.", {
            "prompt": {"type": "string"}, "filename": {"type": "string"},
        }, ["prompt"], self._generate_video, "video")
        self.add("current_time", "Devuelve fecha y hora local del dispositivo.", {}, [], lambda _: datetime.now().astimezone().isoformat(timespec="seconds"), "files")

    def definitions(self) -> list[dict[str, Any]]:
        # The connector label is internal metadata, not part of the provider's function schema.
        return [{"type": item["type"], "function": {k: v for k, v in item["function"].items() if k != "connector"}}
                for item in (tool.definition for tool in self.tools.values())]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if name not in self.tools:
            return f"Error: herramienta no disponible: {name}"
        try:
            return self.tools[name].run(arguments)
        except Exception as exc:
            return f"Error en {name}: {exc}"

    def _list_files(self, args: dict[str, Any]) -> str:
        directory = self._path(args.get("path", "."))
        if not directory.is_dir():
            raise ValueError("No es una carpeta.")
        items = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:200]
        return "\n".join(("📁 " if p.is_dir() else "📄 ") + p.name for p in items) or "(carpeta vacía)"

    def _read_file(self, args: dict[str, Any]) -> str:
        path = self._path(args["path"])
        if path.stat().st_size > 250_000:
            raise ValueError("Archivo demasiado grande (límite 250 KB).")
        return path.read_text(encoding="utf-8", errors="replace")[:30000]

    def _write_file(self, args: dict[str, Any]) -> str:
        path = self._path(args["path"])
        preview = args["content"][:300]
        if not self.confirm(f"Crear/reemplazar {path.relative_to(self.root)} ({len(args['content'])} caracteres).\n{preview}"):
            return "Acción cancelada por el usuario."
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return f"Guardado: {path} ({len(args['content'])} caracteres)"

    def _run_command(self, args: dict[str, Any]) -> str:
        command = args["command"].strip()
        if not command or len(command) > 1200:
            raise ValueError("Comando vacío o demasiado largo.")
        blocked = re.compile(r"\b(rm\s+-rf|mkfs|dd\s+if=|:>\s*/|shutdown|reboot|su\s+-c)\b", re.I)
        if blocked.search(command):
            raise ValueError("Comando bloqueado por seguridad.")
        if not self.confirm(f"Ejecutar en {self.root}:\n$ {command}"):
            return "Comando cancelado por el usuario."
        completed = subprocess.run(command, shell=True, cwd=self.root, capture_output=True, text=True, timeout=60)
        output = (completed.stdout + ("\n" + completed.stderr if completed.stderr else "")).strip()
        return f"exit={completed.returncode}\n{output[:12000]}" or f"exit={completed.returncode} (sin salida)"

    def _web_search(self, args: dict[str, Any]) -> str:
        query = args["query"][:400]
        tavily = self.config.values.get("tavily_key")
        if tavily:
            data = json.loads(_http("https://api.tavily.com/search", method="POST", data={"api_key": tavily, "query": query, "max_results": 5}))
            return "\n\n".join(f"{i+1}. {r.get('title','')}\n{r.get('url','')}\n{r.get('content','')}" for i, r in enumerate(data.get("results", []))) or "Sin resultados."
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        page = _http(url).decode("utf-8", "replace")
        results = re.findall(r'<a rel="nofollow" class="result__a" href="(.*?)"[^>]*>(.*?)</a>', page, re.S)
        snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', page, re.S)
        cleaned = []
        for i, (href, title) in enumerate(results[:6]):
            link = html.unescape(re.sub(r"<.*?>", "", href))
            title = html.unescape(re.sub(r"<.*?>", "", title)).strip()
            snippet = html.unescape(re.sub(r"<.*?>", "", snippets[i])).strip() if i < len(snippets) else ""
            cleaned.append(f"{i+1}. {title}\n{link}\n{snippet}")
        return "\n\n".join(cleaned) or "No se obtuvieron resultados. Configura TERMUXAGENT_TAVILY_KEY para usar Tavily."

    def _fetch_url(self, args: dict[str, Any]) -> str:
        url = _public_url(args["url"])
        raw = _http(url, timeout=30)[:1_000_000].decode("utf-8", "replace")
        raw = re.sub(r"(?is)<(script|style|svg|noscript).*?>.*?</\1>", " ", raw)
        raw = re.sub(r"(?s)<[^>]+>", " ", raw)
        return html.unescape(re.sub(r"\s+", " ", raw)).strip()[:12000]

    def _github_search(self, args: dict[str, Any]) -> str:
        query = urllib.parse.urlencode({"q": args["query"], "sort": "stars", "per_page": 5})
        headers = {"Accept": "application/vnd.github+json"}
        token = self.config.values.get("github_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = json.loads(_http(f"https://api.github.com/search/repositories?{query}", headers=headers))
        return "\n\n".join(f"★ {r['stargazers_count']} {r['full_name']}\n{r.get('description') or ''}\n{r['html_url']}" for r in data.get("items", [])) or "Sin resultados."

    def _github_issue_search(self, args: dict[str, Any]) -> str:
        query = urllib.parse.urlencode({"q": args["query"], "per_page": 5})
        headers = {"Accept": "application/vnd.github+json"}
        token = self.config.values.get("github_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = json.loads(_http(f"https://api.github.com/search/issues?{query}", headers=headers))
        return "\n\n".join(f"{r['title']} [{r['state']}]\n{r['html_url']}\n{r.get('body','')[:500]}" for r in data.get("items", [])) or "Sin resultados."

    def _telegram_send(self, args: dict[str, Any]) -> str:
        token = self.config.values.get("telegram_bot_token")
        chat_id = self.config.values.get("telegram_chat_id")
        message = args["message"][:4000]
        if not token or not chat_id:
            raise ValueError("Configura TERMUXAGENT_TELEGRAM_BOT_TOKEN y TERMUXAGENT_TELEGRAM_CHAT_ID.")
        if not self.confirm(f"Enviar mensaje a Telegram ({chat_id}):\n{message[:300]}"):
            return "Envío cancelado por el usuario."
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        response = json.loads(_http(url, method="POST", data={"chat_id": chat_id, "text": message}, timeout=30))
        if not response.get("ok"):
            raise RuntimeError(str(response.get("description", "Telegram rechazó el mensaje")))
        return "Mensaje enviado a Telegram."

    def _discord_send(self, args: dict[str, Any]) -> str:
        webhook = self.config.values.get("discord_webhook")
        message = args["message"][:1900]
        if not webhook:
            raise ValueError("Configura TERMUXAGENT_DISCORD_WEBHOOK.")
        if not webhook.startswith("https://discord.com/api/webhooks/") and not webhook.startswith("https://discordapp.com/api/webhooks/"):
            raise ValueError("El webhook debe ser una URL HTTPS oficial de Discord.")
        if not self.confirm(f"Enviar mensaje al webhook de Discord:\n{message[:300]}"):
            return "Envío cancelado por el usuario."
        _http(webhook, method="POST", data={"content": message}, timeout=30)
        return "Mensaje enviado a Discord."

    def _android_action(self, args: dict[str, Any]) -> str:
        action = args["action"]
        text = args.get("text", "")
        commands = {
            "open_url": ("termux-open-url", [text]),
            "clipboard": ("termux-clipboard-set", [text]),
            "share": ("termux-share", ["-a", "send", text]),
            "notify": ("termux-notification", ["--title", "TermuxAgent", "--content", text or "Tarea completada"]),
            "location": ("termux-location", ["-p", "network"]),
        }
        binary, extra = commands[action]
        if not shutil.which(binary):
            raise RuntimeError(f"No está instalado {binary}; instala Termux:API y el paquete termux-api.")
        if not self.confirm(f"Ejecutar acción Android: {action} {text[:120]}"):
            return "Acción cancelada por el usuario."
        result = subprocess.run([binary, *extra], capture_output=True, text=True, timeout=60)
        return (result.stdout + result.stderr).strip()[:4000] or f"{action}: completado (exit={result.returncode})"

    def _generate_image(self, args: dict[str, Any]) -> str:
        api_key = self.config.values.get("api_key")
        if not api_key:
            raise ValueError("Configura primero una API key (setup).")
        filename = args.get("filename") or "imagen-generada.png"
        path = self._path(filename)
        if path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise ValueError("Usa una extensión .png, .jpg o .webp.")
        if not self.confirm(f"Generar imagen con el modelo {self.config.image_model} y guardarla en {path.name}."):
            return "Generación cancelada por el usuario."
        url = self.config.base_url.rstrip("/") + "/images/generations"
        payload = {"model": self.config.image_model, "prompt": args["prompt"], "n": 1, "size": "1024x1024"}
        data = json.loads(_http(url, method="POST", data=payload, headers={"Authorization": f"Bearer {api_key}"}, timeout=180))
        item = data["data"][0]
        if item.get("b64_json"):
            image = base64.b64decode(item["b64_json"])
        elif item.get("url"):
            image = _http(item["url"], timeout=120)
        else:
            raise ValueError("El proveedor no devolvió una imagen utilizable.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image)
        return f"Imagen guardada: {path} ({len(image)} bytes)"

    def _generate_video(self, args: dict[str, Any]) -> str:
        token = self.config.values.get("replicate_token")
        model = self.config.values.get("video_model")
        if not token or not model:
            raise ValueError("Configura replicate_token y video_model (por ejemplo, owner/model-version de Replicate) en ~/.termuxagent/config.json.")
        filename = args.get("filename") or "video-generado.mp4"
        path = self._path(filename)
        if path.suffix.lower() != ".mp4":
            raise ValueError("El video debe guardarse con extensión .mp4.")
        if not self.confirm(f"Enviar prompt al modelo de video Replicate {model}; puede incurrir en costes y tardar varios minutos."):
            return "Generación cancelada por el usuario."
        # Model identifier can be owner/name or owner/name:version; both are accepted by Replicate.
        create_url = "https://api.replicate.com/v1/models/" + model + "/predictions"
        headers = {"Authorization": f"Bearer {token}", "Prefer": "wait=60"}
        response = json.loads(_http(create_url, method="POST", data={"input": {"prompt": args["prompt"]}}, headers=headers, timeout=90))
        poll_url = response.get("urls", {}).get("get")
        for _ in range(90):
            if response.get("status") in ("succeeded", "failed", "canceled"):
                break
            if not poll_url:
                break
            import time
            time.sleep(4)
            req = urllib.request.Request(poll_url, headers={"Authorization": f"Bearer {token}", "User-Agent": "TermuxAgent/0.1"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                response = json.loads(resp.read().decode())
        if response.get("status") != "succeeded":
            raise RuntimeError(f"La generación no terminó correctamente (estado: {response.get('status')}). Revisa tu historial en Replicate.")
        output = response.get("output")
        video_url = output[0] if isinstance(output, list) else output
        if not isinstance(video_url, str):
            raise RuntimeError("El modelo no devolvió una URL de video.")
        video = _http(video_url, timeout=180)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(video)
        return f"Video guardado: {path} ({len(video)} bytes)"
