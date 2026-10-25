"""Terminal experience and command-line interface for TermuxAgent."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import APP_DIR, CONFIG_FILE, Config
from .llm import AIError, ChatClient
from .tools import ToolRegistry

RESET = "\033[0m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
DIM = "\033[2m"
BOLD = "\033[1m"

MODES = {
    "chat": "Eres un asistente conversacional útil. Responde con claridad y en el idioma del usuario. No uses herramientas salvo que sean imprescindibles.",
    "agent": "Eres TermuxAgent, un agente autónomo y cuidadoso que se ejecuta con un modelo local. Resuelve tareas usando las herramientas disponibles; explica brevemente lo que haces. No envíes contenido a servicios remotos de IA. Antes de acciones con efectos externos, la herramienta pedirá permiso. Nunca afirmes que hiciste algo si falló.",
    "code": "Eres un agente experto en programación que trabaja en Termux. Inspecciona el workspace antes de cambiarlo, usa herramientas de forma segura, explica decisiones y prueba los cambios cuando sea posible.",
    "research": "Eres un asistente de investigación. Busca en la web, consulta fuentes y presenta una síntesis equilibrada con enlaces. Distingue hechos de incertidumbre y no inventes citas.",
    "creative": "Eres un colaborador creativo para texto, ideas, imágenes y video. Convierte peticiones vagas en propuestas concretas y usa las herramientas multimodales disponibles cuando el usuario lo pida.",
}
MODE_LABELS = {"chat": "Chat", "agent": "Agente", "code": "Código", "research": "Investigación", "creative": "Creativo"}


def _print(text: str = "", color: str = "") -> None:
    print(f"{color}{text}{RESET if color else ''}")


def _confirm(message: str) -> bool:
    _print("\n⚠  Acción que necesita tu permiso", YELLOW)
    print(message)
    try:
        return input("¿Continuar? [s/N] ").strip().lower() in ("s", "si", "sí", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def setup() -> int:
    config = Config.load()
    _print("\n✦ Configuración local de TermuxAgent", CYAN)
    print("TermuxAgent no usa APIs de IA en la nube ni necesita API keys. Primero inicia llama-server en el teléfono.\n")
    base_url = input(f"URL local de llama-server [{config.base_url}]: ").strip() or config.base_url
    from urllib.parse import urlparse
    if urlparse(base_url).hostname not in ("localhost", "127.0.0.1", "::1") or urlparse(base_url).scheme != "http":
        _print("Solo se aceptan direcciones locales (localhost); se mantiene la dirección local predeterminada.", YELLOW)
        base_url = "http://127.0.0.1:8080/v1"
    config.values["base_url"] = base_url
    config.values["model"] = input(f"Identificador del modelo cargado [{config.model}]: ").strip() or config.model
    print("\nMultimedia opcional: ejecuta ComfyUI local y exporta workflows en formato API.")
    comfy_url = input(f"URL local de ComfyUI [{config.comfyui_url}]: ").strip() or config.comfyui_url
    parsed_comfy = urlparse(comfy_url)
    if parsed_comfy.scheme != "http" or parsed_comfy.hostname not in ("localhost", "127.0.0.1", "::1"):
        _print("ComfyUI también debe ejecutarse en localhost; se mantiene su dirección predeterminada.", YELLOW)
        comfy_url = "http://127.0.0.1:8188"
    config.values["comfyui_url"] = comfy_url
    for kind, label in (("image", "imagen"), ("video", "video")):
        config.values[f"{kind}_workflow"] = input(f"Ruta al workflow local de {label} (vacío para omitir): ").strip()
        config.values[f"{kind}_prompt_node"] = input(f"ID del nodo de prompt para {label} (vacío para omitir): ").strip()
    workspace = input(f"Carpeta de trabajo [{config.workspace}]: ").strip()
    if workspace:
        config.values["workspace"] = str(Path(workspace).expanduser().resolve())
    config.save()
    _print(f"\nConfiguración local guardada en {CONFIG_FILE}", GREEN)
    _print("No se guardan ni se envían claves de proveedores de IA.\n", DIM)
    return 0


def _welcome(config: Config) -> None:
    _print("""
╭──────────────────────────────────────────────╮
│  ✦  T E R M U X A G E N T                    │
│     IA local · agente · sin nube              │
╰──────────────────────────────────────────────╯""", CYAN)
    print(f"  Modo: {MODE_LABELS.get(config.mode, config.mode)}  ·  Modelo local: {config.model}")
    print(f"  Workspace: {Path(config.workspace).expanduser()}\n")
    print("  Escribe una tarea o /help para ver comandos.  /quit para salir.\n")


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return ""


class Session:
    def __init__(self, config: Config):
        self.config = config
        self.client = ChatClient(config)
        self.registry = ToolRegistry(config, _confirm)
        self.mode = config.mode if config.mode in MODES else "agent"
        self.messages: list[dict[str, Any]] = []

    def _ask_ai(self, prompt: str) -> str:
        if not self.messages:
            self.messages.append({"role": "system", "content": MODES[self.mode] + f"\n\nWorkspace permitido: {self.registry.root}. Herramientas habilitadas: {', '.join(self.registry.tools)}."})
        self.messages.append({"role": "user", "content": prompt})
        tools = self.registry.definitions() if self.mode in ("agent", "code", "research", "creative") else None
        for _ in range(max(1, min(int(self.config.max_steps), 15))):
            message = self.client.complete(self.messages, tools=tools)
            calls = message.get("tool_calls") or []
            if not calls:
                answer = _content_text(message.get("content")) or "(El modelo no devolvió texto.)"
                self.messages.append({"role": "assistant", "content": answer})
                return answer
            # Preserve the assistant message (including tool call IDs) for API compatibility.
            self.messages.append(message)
            for call in calls:
                function = call.get("function", {})
                name = function.get("name", "")
                try:
                    arguments = json.loads(function.get("arguments", "{}"))
                except json.JSONDecodeError:
                    arguments = {}
                    result = "Error: argumentos JSON inválidos."
                else:
                    _print(f"  ↳ {name}", DIM)
                    result = self.registry.execute(name, arguments)
                self.messages.append({"role": "tool", "tool_call_id": call.get("id", name), "content": result[:16000]})
        self.messages.append({"role": "user", "content": "Continúa con una respuesta final breve; ya se alcanzó el límite de pasos del agente."})
        final = self.client.complete(self.messages)
        answer = _content_text(final.get("content")) or "Límite de pasos alcanzado."
        self.messages.append({"role": "assistant", "content": answer})
        return answer

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            _print("Modos: " + ", ".join(MODES), YELLOW)
            return
        self.mode = mode
        self.config.values["mode"] = mode
        self.config.save()
        self.messages = []
        _print(f"Modo cambiado a {MODE_LABELS[mode]}. Se inició una conversación nueva.", GREEN)

    def command(self, text: str) -> bool:
        cmd, _, arg = text.partition(" ")
        arg = arg.strip()
        if cmd in ("/quit", "/exit", "/salir"):
            _print("¡Hasta luego!", CYAN)
            return False
        if cmd in ("/help", "/ayuda"):
            print("""
Comandos:
  /mode [chat|agent|code|research|creative]  Cambiar modo
  /connectors                                 Ver conectores activos
  /image [prompt]                             Generar imagen directamente
  /video [prompt]                             Generar video directamente
  /clear                                      Limpiar conversación
  /help                                       Mostrar ayuda
  /quit                                       Salir

Cada operación de escritura, shell, Android y generación multimedia pide confirmación.
La IA solo se ejecuta localmente; web/mensajería y otras herramientas conectan a servicios externos si las usas. No hay fallback a una IA en la nube.
""")
            return True
        if cmd == "/mode":
            if not arg:
                print("Modo actual: " + MODE_LABELS.get(self.mode, self.mode) + " · Opciones: " + ", ".join(MODES))
            else:
                self.set_mode(arg.lower())
            return True
        if cmd == "/connectors":
            print("Conectores habilitados: " + (", ".join(sorted({t.definition["function"]["connector"] for t in self.registry.tools.values()})) or "ninguno"))
            print("Herramientas: " + (", ".join(self.registry.tools) or "ninguna"))
            print(f"Configuración: {CONFIG_FILE}")
            return True
        if cmd == "/clear":
            self.messages = []
            _print("Conversación limpiada.", GREEN)
            return True
        if cmd in ("/image", "/video"):
            if not arg:
                print(f"Uso: {cmd} describe lo que quieres crear")
                return True
            tool = "generate_image" if cmd == "/image" else "generate_video"
            result = self.registry.execute(tool, {"prompt": arg})
            _print(result, GREEN if not result.startswith("Error:") else YELLOW)
            return True
        return True

    def run(self) -> int:
        _welcome(self.config)
        while True:
            try:
                text = input(f"{CYAN}{MODE_LABELS.get(self.mode, self.mode)} ❯ {RESET}").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                continue
            if text.startswith("/"):
                if not self.command(text):
                    break
                continue
            try:
                response = self._ask_ai(text)
                _print("\n" + response + "\n", GREEN)
            except (AIError, ValueError) as exc:
                _print(f"\nError: {exc}\n", YELLOW)
            except KeyboardInterrupt:
                print("\nOperación interrumpida.")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="termux-agent", description="Agente de IA multimodal para Termux")
    parser.add_argument("--version", action="version", version=f"TermuxAgent {__version__}")
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("setup", help="Configurar proveedor y claves API")
    chat = sub.add_parser("chat", help="Iniciar el agente interactivo")
    chat.add_argument("--mode", choices=MODES, help="Modo de inicio")
    sub.add_parser("config", help="Mostrar la ruta de configuración (no muestra claves)")
    args = parser.parse_args(argv)
    if args.action == "setup":
        return setup()
    config = Config.load()
    if args.action == "config":
        _print(f"Config: {CONFIG_FILE}\nEndpoint local: {config.base_url}\nModelo local: {config.model}\nComfyUI local: {config.comfyui_url}\nConectores: {', '.join(config.connectors)}")
        return 0
    if args.action == "chat" and args.mode:
        config.values["mode"] = args.mode
    try:
        return Session(config).run()
    except (OSError, ValueError) as exc:
        _print(f"No se pudo iniciar: {exc}", YELLOW)
        return 1


if __name__ == "__main__":
    sys.exit(main())
