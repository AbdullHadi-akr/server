"""Zentrale Konfiguration des Portals (per Umgebungsvariablen steuerbar)."""

import os

# Version des Portals. Wird im Fuss jeder Seite angezeigt - so ist sofort
# erkennbar, ob der Container noch auf einem alten Image laeuft.
VERSION = "2.8 (Abmelden sichtbar)"

# Adresse, unter der das Portal Ollama erreicht (Server-zu-Server). Sie gilt
# fuer alle eigenen Aufrufe: Funktionspruefung, Modelltests, Auslastung.
OLLAMA_URL = os.environ.get(
    "OLLAMA_URL", "http://AZEU-DEW-DEVGPU-02:5020").rstrip("/")

# Adresse, die den Nutzern in der VS-Code-Konfiguration angezeigt wird. Sie
# zeigt auf das Portal selbst (Port 5021), nicht direkt auf Ollama: Nur so
# laufen die Anfragen durch das Portal und lassen sich je Modell zaehlen.
PUBLIC_OLLAMA_URL = os.environ.get(
    "PUBLIC_OLLAMA_URL", "http://azeu-dew-devappl-01:5021").rstrip("/")

# Die zuvor angezeigte Adresse. Sie funktioniert weiter, liefert aber keine
# Zahlen je Modell. Die Einrichtungsseite benennt damit den Wechsel, statt ihn
# stillschweigend zu vollziehen. Leer setzen blendet den Hinweis aus.
ALT_OLLAMA_URL = os.environ.get(
    "ALT_OLLAMA_URL", "http://azeu-dew-devappl-01:5020").rstrip("/")

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

# Optional vorgegebenes Passwort fuer den ersten Admin. Nuetzlich fuer
# automatisierte Installationen; wird nur beim allerersten Start verwendet.
PORTAL_PASSWORT = os.environ.get("PORTAL_PASSWORT", "")

# Gueltigkeit einer Anmeldung in Sekunden (verlaengert sich bei Nutzung).
SITZUNGSDAUER = float(os.environ.get("SITZUNGSDAUER", "28800"))

# So viele Log-Zeilen wertet die Auslastungsanzeige aus.
LOG_ZEILEN = int(os.environ.get("LOG_ZEILEN", "4000"))

# --- Proxy ------------------------------------------------------------------
# Vorgeschalteter Proxy auf eigenem Port. Zeigt PUBLIC_OLLAMA_URL darauf,
# laufen die Anfragen durch das Portal und lassen sich je Modell zaehlen.
# Vorgeschalteter Proxy: Anfragen laufen durch das Portal und lassen sich je
# Modell zaehlen. Standardmaessig am selben Port wie das Portal - was keine
# Portal-Route und keine Datei ist, geht an Ollama weiter. Ein abweichender
# PROXY_PORT startet stattdessen einen zweiten Listener.
PROXY_AKTIV = os.environ.get("PROXY_AKTIV", "true").lower() in (
    "1", "true", "yes", "ja")
PROXY_PORT = int(os.environ.get("PROXY_PORT", str(PORT)))
# Zeitlimit fuer den Verbindungsaufbau zu Ollama. Auf die Antwort wird
# unbegrenzt gewartet - Generierungen dauern lange.
PROXY_TIMEOUT = float(os.environ.get("PROXY_TIMEOUT", "30"))

# Muessen Chat-Anfragen einen gueltigen Zugangsschluessel mitbringen?
# Standard ist der Duldungsmodus: Anfragen ohne Schluessel laufen weiter durch
# und werden als "(ohne Token)" gezaehlt. Erst umschalten, wenn die Uebersicht
# zeigt, dass niemand mehr ohne Schluessel kommt - sonst bricht der Chat.
TOKEN_PFLICHT = os.environ.get("TOKEN_PFLICHT", "false").lower() in (
    "1", "true", "yes", "ja")

# --- Reservierungen ---------------------------------------------------------
RESERVIERUNG_MAX_STUNDEN = float(os.environ.get("RESERVIERUNG_MAX_STUNDEN", "4"))
# So viele Slots je Modell bleiben fuer alle anderen frei; Admins duerfen
# darueber hinaus reservieren.
RESERVIERUNG_MIN_FREI = int(os.environ.get("RESERVIERUNG_MIN_FREI", "1"))

# --- Verlauf ----------------------------------------------------------------
# Aufzeichnung der Messwerte in /data/verlauf.sqlite.
VERLAUF_AKTIV = os.environ.get("VERLAUF_AKTIV", "true").lower() in (
    "1", "true", "yes", "ja")
VERLAUF_TAKT = int(os.environ.get("VERLAUF_TAKT", "60"))
VERLAUF_TAGE = int(os.environ.get("VERLAUF_TAGE", "30"))

# --- GPU --------------------------------------------------------------------
GPU_NAME = os.environ.get("GPU_NAME", "NVIDIA A100")
# Rueckfallwert: Wird nur genutzt, wenn nvidia-smi im Ollama-Container
# nicht erreichbar ist. Sonst gilt der gemessene Wert.
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
        "maxInputTokens": 50000,
        "maxOutputTokens": 16000,
        "beschreibung": "Allrounder fuer Chat, Analyse und Fragen zum Code.",
    },
    {
        "id": "qwen3-coder:30b",
        "name": f"qwen3-coder ({VENDOR_NAME})",
        "toolCalling": True,
        "vision": False,
        "maxInputTokens": 50000,
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
