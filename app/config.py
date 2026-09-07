"""Zentrale Konfiguration des Portals (per Umgebungsvariablen steuerbar)."""

import os

# Adresse, unter der das Portal Ollama erreicht (Server-zu-Server).
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://AZEU-DEW-DEVGPU-02:5020").rstrip("/")

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
