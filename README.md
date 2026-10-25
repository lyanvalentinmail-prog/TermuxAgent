# TermuxAgent ✦

Un agente de IA **multimodal, modular y pensado para ejecutarse en Android con Termux**. Incluye chat y uso de herramientas, varios modos de trabajo, conectores para Android/web/GitHub/archivos, generación de imágenes y generación de video opcional. No requiere dependencias Python externas.

> La aplicación es el agente local; para conversar y generar medios necesitas configurar proveedores y sus propias API keys. Algunos proveedores cobran por uso. TermuxAgent no incluye ni comparte claves.

## Instalación en Termux

Instala [Termux desde F-Droid o GitHub](https://github.com/termux/termux-app) y ejecuta:

```sh
pkg update -y
pkg install -y python git
# Opcional: acciones del teléfono (abrir enlaces, portapapeles, notificaciones, ubicación)
pkg install -y termux-api
python -m pip install --upgrade pip
python -m pip install git+https://github.com/lyanvalentinmail-prog/TermuxAgent.git
termux-agent setup
termux-agent
```

Si instalas desde una copia del proyecto:

```sh
cd TermuxAgent
python -m pip install .
termux-agent setup
```

Para dar acceso a archivos compartidos del teléfono, ejecuta `termux-setup-storage` en Termux y en `setup` elige `~/storage/shared` como carpeta de trabajo.

## Configuración del modelo

El asistente de `termux-agent setup` solicita una API compatible con el formato OpenAI Chat Completions. La configuración queda en `~/.termuxagent/config.json` con permisos `600`. No guardes ese archivo en repositorios públicos. También puedes suministrar las claves mediante variables de entorno:

```sh
export TERMUXAGENT_API_KEY="..."
export TERMUXAGENT_BASE_URL="https://openrouter.ai/api/v1"
export TERMUXAGENT_MODEL="openai/gpt-4o-mini"
```

Variables opcionales:

| Variable | Uso |
|---|---|
| `TERMUXAGENT_API_KEY` (o `OPENAI_API_KEY`) | Chat y generación de imágenes |
| `TERMUXAGENT_BASE_URL` | Endpoint compatible con OpenAI |
| `TERMUXAGENT_MODEL` | Modelo de chat/herramientas |
| `TERMUXAGENT_IMAGE_MODEL` | Modelo de imágenes compatible con `/images/generations` |
| `TERMUXAGENT_REPLICATE_TOKEN` | Generación de videos con Replicate |
| `TERMUXAGENT_TAVILY_KEY` | Búsquedas web con Tavily; sin clave intenta DuckDuckGo |
| `GITHUB_TOKEN` | Aumenta el límite de búsquedas de GitHub |
| `TERMUXAGENT_HOME` | Cambia la carpeta privada de configuración |

La generación de videos requiere además establecer `video_model` en `~/.termuxagent/config.json` con un modelo de Replicate compatible con entrada `prompt` y salida de video. La disponibilidad, parámetros y coste dependen del modelo. El agente pide confirmación antes de iniciar la generación.

## Modos

- **agent** (por defecto): delega tareas y utiliza conectores con confirmación cuando corresponde.
- **chat**: conversación sencilla, sin herramientas.
- **code**: ayuda de programación en el workspace, con herramientas de archivos y terminal.
- **research**: investigación y síntesis apoyada en búsqueda web.
- **creative**: ideas, escritura e imágenes/video.

```sh
termux-agent chat --mode research
# o desde la sesión:
/mode creative
```

## Conectores incluidos

- **Archivos**: listar, leer y crear/editar archivos dentro del workspace.
- **Shell de Termux**: comandos con autorización explícita.
- **Web**: búsqueda (Tavily o alternativa DuckDuckGo) y lectura de páginas públicas.
- **GitHub**: búsqueda de repositorios e issues/pull requests públicos.
- **Telegram y Discord**: envío de mensajes con bot/chat o webhook configurados; pide autorización antes de enviar.
- **Android/Termux:API**: abrir URL, portapapeles, compartir texto, notificación y ubicación (requiere permisos/utilidades de Termux:API).
- **Imágenes**: genera y guarda PNG/JPG mediante endpoint OpenAI-compatible.
- **Video**: genera y descarga MP4 mediante Replicate, si se configura.
- **Utilidad**: fecha/hora local.

Las herramientas se pueden habilitar/deshabilitar editando `connectors` en `~/.termuxagent/config.json`. Se pueden sumar conectores implementando nuevas herramientas en `src/termuxagent/tools.py`.

## Uso

En la sesión interactiva escribe una tarea en lenguaje natural. Comandos disponibles:

```text
/help                 Ayuda
/mode agent           Cambiar modo
/connectors           Ver conectores y herramientas activos
/image un zorro...    Generar una imagen
/video un paisaje...  Generar un video
/clear                Nueva conversación
/quit                 Salir
```

Los archivos generados se guardan en el workspace. También puedes ejecutar `termux-agent config` para ver configuración no secreta y `termux-agent --version` para consultar versión.

## Seguridad y privacidad

- Las acciones de escritura, shell, integración Android e imagen/video requieren confirmación en pantalla.
- Los accesos de archivos se limitan al workspace configurado; lectura de archivos hasta 250 KB y salida acotada.
- Comandos de shell se ejecutan en el dispositivo, no en un servidor remoto. Revisa el comando antes de aprobarlo; no apruebes órdenes que no entiendas.
- La búsqueda y el modelo envían el texto necesario al proveedor seleccionado. No incluyas secretos en prompts.
- Algunas acciones Android necesitan que instales la app **Termux:API**, otorgues permisos y ejecutes `pkg install termux-api`.

## Desarrollo

```sh
python -m unittest discover -s tests -v
python -m termuxagent --help
```

Licencia: MIT.
