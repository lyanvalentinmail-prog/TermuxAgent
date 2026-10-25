"""Built-in connectors exposed to the agent as OpenAI-compatible function tools."""
from __future__ import annotations

import html
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import time
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
    hdrs = {"User-Agent": "TermuxAgent/0.2-local"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    else:
        opener = urllib.request.build_opener()
    with opener.open(req, timeout=timeout) as response:
        return response.read()


def _local_service_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Las herramientas de generación solo se conectan a servidores locales en localhost.")
    return url.rstrip("/")


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
        self.add("web_search", "Busca información en la web (DuckDuckGo; sin proveedor de búsqueda con IA).", {"query": {"type": "string"}}, ["query"], self._web_search, "web")
        self.add("fetch_url", "Obtiene el texto de una página pública http(s), sin acceder a direcciones privadas.", {"url": {"type": "string"}}, ["url"], self._fetch_url, "web")
        self.add("github_search", "Busca repositorios públicos de GitHub.", {"query": {"type": "string"}}, ["query"], self._github_search, "github")
        self.add("github_issue_search", "Busca issues y pull requests públicos en GitHub.", {"query": {"type": "string"}}, ["query"], self._github_issue_search, "github")
        self.add("telegram_send", "Envía un mensaje a Telegram usando un bot y chat configurados. Siempre pide confirmación.", {"message": {"type": "string"}}, ["message"], self._telegram_send, "telegram")
        self.add("discord_send", "Envía un mensaje a un canal de Discord mediante un webhook configurado. Siempre pide confirmación.", {"message": {"type": "string"}}, ["message"], self._discord_send, "discord")
        self.add("android_action", "Usa utilidades opcionales de Termux: abrir URL, copiar texto, compartir texto, notificación o ubicación. Requiere Termux:API para algunas acciones.", {
            "action": {"type": "string", "enum": ["open_url", "clipboard", "share", "notify", "location"]},
            "text": {"type": "string", "description": "URL, texto, o título de notificación según acción"},
        }, ["action"], self._android_action, "android")
        self.add("generate_image", "Genera una imagen usando un workflow local de ComfyUI. No utiliza APIs ni modelos de IA en la nube.", {
            "prompt": {"type": "string"}, "filename": {"type": "string", "description": "Nombre .png/.jpg opcional"},
        }, ["prompt"], self._generate_image, "image")
        self.add("generate_video", "Genera un video con un workflow local de ComfyUI. No utiliza APIs ni modelos de IA en la nube.", {
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
        return "\n\n".join(cleaned) or "No se obtuvieron resultados."

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

    def _comfyui_generate(self, args: dict[str, Any], kind: str) -> str:
        cfg = self.config.values
        workflow_key = f"{kind}_workflow"
        node_key = f"{kind}_prompt_node"
        workflow_path = Path(str(cfg.get(workflow_key, ""))).expanduser()
        if not str(cfg.get(workflow_key, "")).strip() or not workflow_path.is_file():
            raise ValueError(f"Configura {workflow_key} con el workflow API de ComfyUI (archivo JSON local).")
        node_id = str(cfg.get(node_key, "")).strip()
        if not node_id:
            raise ValueError(f"Configura {node_key} con el ID del nodo de texto/prompt en el workflow.")
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        node = workflow.get(node_id)
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            raise ValueError(f"El nodo {node_id} no existe o no tiene inputs en el workflow API.")
        inputs = node["inputs"]
        prompt_field = str(cfg.get(f"{kind}_prompt_field", ""))
        if not prompt_field:
            prompt_field = "text" if "text" in inputs else "prompt" if "prompt" in inputs else ""
        if prompt_field not in inputs:
            raise ValueError(f"No se encontró el campo de prompt. Configura {kind}_prompt_field en config.json.")
        inputs[prompt_field] = args["prompt"]
        endpoint = _local_service_url(str(cfg.get("comfyui_url", "")))
        filename = args.get("filename") or ("imagen-generada.png" if kind == "image" else "video-generado.mp4")
        output_path = self._path(filename)
        allowed_extensions = (".png", ".jpg", ".jpeg", ".webp") if kind == "image" else (".mp4", ".webm", ".gif")
        if output_path.suffix.lower() not in allowed_extensions:
            raise ValueError(f"Extensión no admitida. Usa: {', '.join(allowed_extensions)}.")
        if not self.confirm(f"Generar {kind} localmente con ComfyUI en el dispositivo. Esto puede tardar y usar mucha memoria."):
            return "Generación cancelada por el usuario."
        response = json.loads(_http(endpoint + "/prompt", method="POST", data={"prompt": workflow}, timeout=60))
        prompt_id = response.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI no aceptó el workflow: {str(response)[:600]}")
        history_entry: dict[str, Any] | None = None
        for _ in range(360):
            time.sleep(2)
            history = json.loads(_http(endpoint + "/history/" + urllib.parse.quote(str(prompt_id)), timeout=30))
            history_entry = history.get(str(prompt_id))
            if history_entry:
                status = history_entry.get("status", {})
                if status.get("status_str") in ("error", "interrupted"):
                    raise RuntimeError("ComfyUI no pudo completar el workflow local.")
                outputs = history_entry.get("outputs", {})
                keys = ("images",) if kind == "image" else ("videos", "gifs", "images")
                candidates = [(key, item) for output in outputs.values() for key in keys for item in output.get(key, [])]
                if candidates:
                    output_type, item = candidates[0]
                    source_ext = Path(item.get("filename", "")).suffix.lower()
                    if source_ext and output_path.suffix.lower() != source_ext:
                        raise ValueError(f"El workflow produjo {source_ext}; cambia el nombre de salida para usar esa extensión.")
                    params = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")})
                    media = _http(endpoint + "/view?" + params, timeout=180)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(media)
                    return f"{kind.capitalize()} guardado localmente: {output_path} ({len(media)} bytes)"
        raise TimeoutError(f"Tiempo de espera agotado para el workflow local de ComfyUI ({prompt_id}).")

    def _generate_image(self, args: dict[str, Any]) -> str:
        return self._comfyui_generate(args, "image")

    def _generate_video(self, args: dict[str, Any]) -> str:
        return self._comfyui_generate(args, "video")
