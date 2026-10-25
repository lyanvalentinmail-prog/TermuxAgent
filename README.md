# TermuxAgent ✦

Agente de inteligencia artificial diseñado para ejecutarse en Android/Termux **sin enviar prompts a proveedores de IA en la nube**. El chat y las decisiones del agente usan un servidor local `llama.cpp`; imágenes y videos pueden generarse con workflows locales de ComfyUI. No hay fallback a OpenAI, OpenRouter, Replicate ni Tavily.

## Importante: qué significa “nuestra IA”

El código del agente y su configuración son de este proyecto y la inferencia se mantiene en el dispositivo. Para que responda, necesita pesos de un modelo de lenguaje en formato GGUF que tú eliges y descargas; TermuxAgent **no es un modelo fundacional entrenado desde cero**. Entrenar uno propio requiere datasets y mucha más capacidad de cómputo que un teléfono. Un modelo abierto usado localmente no envía las conversaciones a su proveedor.

## Instalación en Termux

1. Instala Termux desde F-Droid o GitHub y prepara las herramientas de compilación:

```sh
pkg update -y
pkg install -y python git cmake clang make
```

2. Compila `llama.cpp` en el dispositivo y prepara una carpeta de modelos:

```sh
git clone https://github.com/ggml-org/llama.cpp "$HOME/llama.cpp"
cmake -S "$HOME/llama.cpp" -B "$HOME/llama.cpp/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$HOME/llama.cpp/build" --config Release -j 2
mkdir -p "$HOME/models"
```

Descarga manualmente un modelo **GGUF** compatible con `llama.cpp` y colócalo como `~/models/assistant.gguf`. Para usar herramientas en modo agente, elige un modelo instruct/chat con plantilla compatible con tool calling. El tamaño del modelo determina el uso de RAM, almacenamiento y velocidad. Empieza con un modelo cuantizado pequeño que sea compatible con la memoria disponible en tu teléfono.

3. Inicia el servidor local (mantén esta sesión de Termux abierta):

```sh
"$HOME/llama.cpp/build/bin/llama-server" \
  -m "$HOME/models/assistant.gguf" \
  --host 127.0.0.1 --port 8080 -c 2048
```

4. En otra sesión de Termux instala y configura TermuxAgent:

```sh
python -m pip install git+https://github.com/lyanvalentinmail-prog/TermuxAgent.git
termux-agent setup
termux-agent
```

El endpoint predeterminado es `http://127.0.0.1:8080/v1`. **Solo acepta localhost**: si el servidor local no está corriendo, el agente muestra un error y no intenta usar una IA remota.

Para instalar desde una copia del repositorio:

```sh
cd TermuxAgent
python -m pip install .
```

## Imágenes y videos, también locales

La generación multimedia usa workflows de **ComfyUI local**, no una API de generación remota. Debes instalar/configurar ComfyUI en el dispositivo, descargar los modelos que necesite y guardar workflows en formato API. En `termux-agent setup` especifica la URL local de ComfyUI (por defecto `http://127.0.0.1:8188`), la ruta de cada workflow JSON y el ID del nodo que contiene el prompt. ComfyUI puede consumir bastante RAM, almacenamiento y batería; la generación de video local puede ser demasiado pesada para muchos teléfonos.

Si no configuras workflows, chat y agente siguen funcionando, pero las herramientas de imagen/video informarán que no están listas. TermuxAgent solo llama al endpoint de ComfyUI en localhost. Para mantener la generación verdaderamente sin nube, usa workflows y nodos locales: algunos nodos personalizados de ComfyUI pueden conectarse a servicios externos por su cuenta.

## Modos

- **agent**: resuelve tareas usando las herramientas locales habilitadas.
- **chat**: conversación sin herramientas.
- **code**: programación sobre el workspace.
- **research**: búsqueda web y síntesis; el modelo sigue siendo local.
- **creative**: apoyo creativo con workflows locales de imagen/video.

```sh
termux-agent chat --mode research
# dentro de la sesión:
/mode creative
```

## Conectores

- **Archivos**: listar, leer y escribir dentro del workspace.
- **Shell**: ejecutar comandos en Termux con aprobación explícita.
- **Web**: DuckDuckGo HTML y lectura de páginas públicas (no usa un buscador con IA).
- **GitHub**: búsqueda de repositorios/issues.
- **Android/Termux:API**: abrir URL, portapapeles, compartir texto, notificación y ubicación.
- **Telegram/Discord**: envío de mensajes si configuras credenciales, siempre con confirmación.
- **ComfyUI local**: workflows locales de imagen/video.

Los conectores pueden activarse/desactivarse en `connectors` dentro de `~/.termuxagent/config.json`. Aunque GitHub, web, Telegram y Discord necesitan conectividad con sus servicios, **no sustituyen ni reciben los prompts del modelo**; los mensajes que envíes a estos servicios se transmiten solo si invocas esas herramientas y apruebas la acción.

Para algunas acciones Android, instala también la app Termux:API y el paquete:

```sh
pkg install -y termux-api
termux-setup-storage  # opcional, para acceder al almacenamiento compartido
```

## Configuración

`termux-agent setup` no pide ni guarda claves de IA. Archivo de configuración: `~/.termuxagent/config.json` (permisos 600).

Variables opcionales:

| Variable | Uso |
|---|---|
| `TERMUXAGENT_LOCAL_URL` | Endpoint local de llama-server; solo localhost |
| `TERMUXAGENT_LOCAL_MODEL` | Nombre del modelo cargado por el servidor |
| `TERMUXAGENT_COMFYUI_URL` | Endpoint local de ComfyUI; solo localhost |
| `GITHUB_TOKEN` | Aumenta el límite de búsqueda de GitHub |
| `TERMUXAGENT_TELEGRAM_BOT_TOKEN` y `TERMUXAGENT_TELEGRAM_CHAT_ID` | Envío a Telegram |
| `TERMUXAGENT_DISCORD_WEBHOOK` | Envío a Discord |

## Uso

```text
/help                  Mostrar ayuda
/mode agent            Cambiar modo
/connectors            Ver conectores activos
/image un zorro...     Generar imagen localmente
/video un paisaje...   Generar video localmente
/clear                 Limpiar conversación
/quit                  Salir
```

Las escrituras, shell, Android, mensajes externos y generación multimedia piden confirmación. Los archivos se limitan al workspace configurado.

## Desarrollo

```sh
python -m unittest discover -s tests -v
python -m compileall -q src
```

Licencia: MIT.
