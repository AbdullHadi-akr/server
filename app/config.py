"""Zentrale Konfiguration des Portals (per Umgebungsvariablen steuerbar)."""

import os

# Version des Portals. Wird im Fuss jeder Seite angezeigt - so ist sofort
# erkennbar, ob der Container noch auf einem alten Image laeuft.
VERSION = "1.5 (Slots je Modell)"

# Adresse, unter der das Portal Ollama erreicht (Server-zu-Server).
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://azeu-dew-devappl-01:5020").rstrip("/")

# Adresse, die den Nutzern in der VS-Code-Konfiguration angezeigt wird.
# Standardmaessig identisch mit OLLAMA_URL, kann aber abweichen, wenn das
# Portal Ollama ueber einen internen Namen erreicht, die Clients aber nicht.
PUBLIC_OLLAMA_URL = os.environ.get("PUBLIC_OLLAMA_URL", OLLAMA_URL).rstrip("/")

# Name des Anbieter-Eintrags in der chatLanguageModels.json.
VENDOR_NAME = os.environ.get("VENDOR_NAME", "A100")

PORT = int(os.environ.get("PORT", "5021"))
HOST = os.environ.get("HOST", "0.0.0.0")

# Timeouts in Sekunden. Der Chat-Timeout ist grosszuegig, weil Ollama das
# Modell beim ersten Aufruf erst in den GPU-Speicher laden muss.
PROBE_TIMEOUT = float(os.environ.get("PROBE_TIMEOUT", "10"))
CHAT_TIMEOUT = float(os.environ.get("CHAT_TIMEOUT", "300"))

# --- Steuerung des Ollama-Containers ---------------------------------------
# Name (oder ID) des Containers, in dem Ollama laeuft. Kommt bewusst nur aus
# der Umgebung und nie aus der Anfrage des Browsers.
CONTAINER_NAME = os.environ.get("OLLAMA_CONTAINER", "ollama")
DOCKER_SOCKET = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
DOCKER_TIMEOUT = float(os.environ.get("DOCKER_TIMEOUT", "20"))

# Schreibende Aktionen (Start/Stopp/Neustart, Einstellungen uebernehmen).
# Auf "false" setzen, um die Betriebsseite auf Nur-Lesen zu beschraenken.
DOCKER_STEUERUNG = os.environ.get("DOCKER_STEUERUNG", "true").lower() in (
    "1", "true", "yes", "ja")

# --- Anmeldung an der Einstellungsseite ------------------------------------
# Verzeichnis fuer dauerhafte Daten (Passwort-Hash). Muss als Volume
# eingebunden sein, sonst ist das Passwort nach einem Neustart weg.
DATEN_DIR = os.environ.get("DATEN_VERZEICHNIS", "/data")

# Optional fest vorgegebenes Passwort. Ist es gesetzt, entfaellt die
# Ersteinrichtung im Browser und das Passwort laesst sich dort nicht aendern.
PORTAL_PASSWORT = os.environ.get("PORTAL_PASSWORT", "")

# Gueltigkeit einer Anmeldung in Sekunden (verlaengert sich bei Nutzung).
SITZUNGSDAUER = float(os.environ.get("SITZUNGSDAUER", "28800"))

# So viele Log-Zeilen wertet die Auslastungsanzeige aus.
LOG_ZEILEN = int(os.environ.get("LOG_ZEILEN", "4000"))

# --- GPU --------------------------------------------------------------------
GPU_NAME = os.environ.get("GPU_NAME", "NVIDIA A100")
GPU_VRAM_GIB = float(os.environ.get("GPU_VRAM_GIB", "80"))

# Standardwerte, wie sie aktuell im Ollama-Container gesetzt sind.
STANDARD_PARALLEL = int(os.environ.get("STANDARD_PARALLEL", "4"))
STANDARD_KONTEXT = int(os.environ.get("STANDARD_KONTEXT", "50000"))

MODELS = [
    {
        "id": "qwen3:30b-a3b",
        "name": f"qwen3 ({VENDOR_NAME})",
        "toolCalling": True,
        "vision": False,
        "maxInputTokens": 128000,
        "maxOutputTokens": 16000,
        "beschreibung": "Allrounder fuer Chat, Analyse und Fragen zum Code.",
    },
    {
        "id": "qwen3-coder:30b",
        "name": f"qwen3-coder ({VENDOR_NAME})",
        "toolCalling": True,
        "vision": False,
        "maxInputTokens": 128000,
        "maxOutputTokens": 16000,
        "beschreibung": "Auf Programmierung und Agenten-/Tool-Aufrufe optimiert.",
    },
]


def vscode_config():
    """Erzeugt den Inhalt der chatLanguageModels.json."""
    return [
        {
            "name": VENDOR_NAME,
            "vendor": "customendpoint",
            "apiType": "chat-completions",
            "models": [
                {
                    "id": m["id"],
                    "name": m["name"],
                    "url": PUBLIC_OLLAMA_URL,
                    "toolCalling": m["toolCalling"],
                    "vision": m["vision"],
                    "maxInputTokens": m["maxInputTokens"],
                    "maxOutputTokens": m["maxOutputTokens"],
                }
                for m in MODELS
            ],
        }
    ]
