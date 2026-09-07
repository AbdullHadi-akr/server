"""HTTP-Server des Portals: statische Seite plus Diagnose-API."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config, ollama

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "ModellPortal/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # kompaktes Log-Format
        print(f"{self.address_string()} {fmt % args}", flush=True)

    # -- Hilfsfunktionen -------------------------------------------------
    def _send(self, status, body, content_type):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, daten, status=200):
        self._send(status, json.dumps(daten, ensure_ascii=False, indent=2),
                   "application/json; charset=utf-8")

    def _static(self, name):
        pfad = os.path.join(STATIC_DIR, name)
        # Pfad-Ausbruch verhindern.
        if not os.path.abspath(pfad).startswith(STATIC_DIR) or not os.path.isfile(pfad):
            self._send(404, "Nicht gefunden", "text/plain; charset=utf-8")
            return
        with open(pfad, "rb") as datei:
            inhalt = datei.read()
        endung = os.path.splitext(pfad)[1]
        self._send(200, inhalt, CONTENT_TYPES.get(endung, "application/octet-stream"))

    # -- Routen ----------------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        route = urlparse(self.path)
        pfad = route.path.rstrip("/") or "/"

        if pfad == "/":
            self._static("index.html")
        elif pfad == "/healthz":
            # Schlanker Endpunkt fuer den Docker-Healthcheck.
            self._json({"status": "ok"})
        elif pfad == "/api/modelle":
            self._json({
                "ollamaUrl": config.OLLAMA_URL,
                "publicUrl": config.PUBLIC_OLLAMA_URL,
                "vendor": config.VENDOR_NAME,
                "modelle": config.MODELS,
            })
        elif pfad == "/api/vscode-config":
            self._json(config.vscode_config())
        elif pfad == "/api/diagnose":
            self._json(ollama.diagnose())
        elif pfad == "/api/test":
            parameter = parse_qs(route.query)
            model_id = (parameter.get("model") or [""])[0]
            treffer = next((m for m in config.MODELS if m["id"] == model_id), None)
            if treffer is None:
                self._json({"ok": False, "fehler": f"Unbekanntes Modell: {model_id}"}, 400)
                return
            self._json(ollama.chat_test(treffer["id"], treffer["toolCalling"]))
        else:
            self._static(pfad.lstrip("/"))


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    server = Server((config.HOST, config.PORT), Handler)
    print(f"Portal laeuft auf http://{config.HOST}:{config.PORT}", flush=True)
    print(f"Ollama-Backend: {config.OLLAMA_URL}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Beende Portal", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
