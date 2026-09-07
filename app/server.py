"""HTTP-Server des Portals: statische Seiten, Diagnose- und Betriebs-API."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import auth, config, dockerctl, nutzung, ollama, vram

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}

# Groesster akzeptierter Anfragerumpf - die Nutzlasten hier sind winzig.
MAX_RUMPF = 64 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "ModellPortal/1.3"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # kompaktes Log-Format
        print(f"{self.address_string()} {fmt % args}", flush=True)

    # -- Hilfsfunktionen -------------------------------------------------
    def _send(self, status, body, content_type, cookie=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        if cookie is not None:
            self._setze_cookie(*cookie)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, daten, status=200, cookie=None):
        self._send(status, json.dumps(daten, ensure_ascii=False, indent=2),
                   "application/json; charset=utf-8", cookie=cookie)

    def _fehler(self, meldung, status=400):
        self._json({"ok": False, "fehler": meldung}, status)

    def _rumpf(self):
        """Liest den JSON-Rumpf der Anfrage."""
        laenge = int(self.headers.get("Content-Length") or 0)
        if laenge <= 0:
            return {}
        if laenge > MAX_RUMPF:
            raise ValueError("Anfrage ist zu gross")
        return json.loads(self.rfile.read(laenge).decode("utf-8"))

    def _sitzung(self):
        """Liest das Sitzungs-Token aus dem Cookie der Anfrage."""
        rohcookie = self.headers.get("Cookie", "")
        for teil in rohcookie.split(";"):
            name, _, wert = teil.strip().partition("=")
            if name == "portal_sitzung":
                return wert
        return ""

    def _angemeldet(self):
        return auth.gueltig(self._sitzung())

    def _adresse(self):
        return self.client_address[0] if self.client_address else "unbekannt"

    def _darf_schreiben(self):
        """Prueft Anmeldung und Freischaltung der Steuerung."""
        if not self._angemeldet():
            self._fehler("Nicht angemeldet.", 401)
            return False
        if not config.DOCKER_STEUERUNG:
            self._fehler("Die Steuerung ist deaktiviert (DOCKER_STEUERUNG=false).", 403)
            return False
        return True

    def _setze_cookie(self, token, dauer):
        """Sitzungs-Cookie setzen oder loeschen (dauer=0)."""
        # HttpOnly: kein Zugriff aus JavaScript. Kein Secure-Flag, weil das
        # Portal im internen Netz ueber http ausgeliefert wird.
        self.send_header(
            "Set-Cookie",
            f"portal_sitzung={token}; HttpOnly; Path=/; SameSite=Strict; "
            f"Max-Age={int(dauer)}")

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

    # -- Lesende Routen --------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        route = urlparse(self.path)
        pfad = route.path.rstrip("/") or "/"
        parameter = parse_qs(route.query)

        if pfad == "/":
            self._static("index.html")
        elif pfad == "/betrieb":
            self._static("betrieb.html")
        elif pfad == "/uebersicht":
            self._static("uebersicht.html")
        elif pfad == "/healthz":
            # Schlanker Endpunkt fuer den Docker-Healthcheck.
            self._json({"status": "ok", "version": config.VERSION,
                        "seiten": ["/", "/betrieb"]})
        elif pfad == "/api/modelle":
            self._json({
                "ollamaUrl": config.OLLAMA_URL,
                "publicUrl": config.PUBLIC_OLLAMA_URL,
                "vendor": config.VENDOR_NAME,
                "version": config.VERSION,
                "modelle": config.MODELS,
            })
        elif pfad == "/api/vscode-config":
            self._json(config.vscode_config())
        elif pfad == "/api/diagnose":
            self._json(ollama.diagnose())
        elif pfad == "/api/test":
            self._modelltest(parameter)
        elif pfad == "/api/geladen":
            self._json(ollama.geladene_modelle())
        elif pfad == "/api/docker/status":
            self._docker_status()
        elif pfad == "/api/docker/logs":
            self._docker_logs(parameter)
        elif pfad == "/api/vram":
            self._vram(parameter)
        elif pfad == "/api/nutzung":
            self._nutzung()
        elif pfad == "/api/auth/status":
            self._json({"ok": True, "angemeldet": self._angemeldet(),
                        "steuerungAktiv": config.DOCKER_STEUERUNG,
                        **auth.zustand()})
        else:
            self._static(pfad.lstrip("/"))

    def _modelltest(self, parameter):
        model_id = (parameter.get("model") or [""])[0]
        treffer = next((m for m in config.MODELS if m["id"] == model_id), None)
        if treffer is None:
            self._fehler(f"Unbekanntes Modell: {model_id}")
            return
        self._json(ollama.chat_test(treffer["id"], treffer["toolCalling"]))

    def _docker_status(self):
        try:
            self._json({"ok": True, **dockerctl.status()})
        except dockerctl.DockerFehler as fehler:
            self._json({"ok": False, "fehler": str(fehler),
                        "portalDarfSteuern": config.DOCKER_STEUERUNG,
                        "container": config.CONTAINER_NAME}, 200)

    def _docker_logs(self, parameter):
        # Logs koennen Adressen und Fehlermeldungen enthalten und bleiben
        # daher der Einstellungsseite vorbehalten.
        if not self._angemeldet():
            self._fehler("Nicht angemeldet.", 401)
            return
        try:
            zeilen = int((parameter.get("zeilen") or ["200"])[0])
        except ValueError:
            zeilen = 200
        try:
            self._json({"ok": True, "text": dockerctl.logs(zeilen)})
        except dockerctl.DockerFehler as fehler:
            self._json({"ok": False, "fehler": str(fehler)}, 200)

    def _vram(self, parameter):
        try:
            parallel = int((parameter.get("parallel")
                            or [config.STANDARD_PARALLEL])[0])
            kontext = int((parameter.get("kontext") or [config.STANDARD_KONTEXT])[0])
            gleichzeitig = int((parameter.get("modelle") or ["1"])[0])
        except ValueError:
            self._fehler("Nutzeranzahl, Kontext und Modellzahl muessen Zahlen sein.")
            return
        kv_typ = (parameter.get("kv") or ["f16"])[0]
        meldung = vram.pruefe_eingaben(parallel, kontext, kv_typ)
        if meldung:
            self._fehler(meldung)
            return
        if not 1 <= gleichzeitig <= len(vram.MODELLE):
            self._fehler("Es koennen 1 oder 2 Modelle gleichzeitig geladen sein.")
            return
        self._json({
            "ok": True,
            "gpu": config.GPU_NAME,
            **vram.uebersicht(parallel, kontext, kv_typ,
                              config.GPU_VRAM_GIB, gleichzeitig),
            "standard": {"parallel": config.STANDARD_PARALLEL,
                         "kontext": config.STANDARD_KONTEXT},
            "kvTypen": vram.KV_TYPEN,
            "grenzen": {"maxParallel": vram.MAX_PARALLEL,
                        "minKontext": vram.MIN_KONTEXT,
                        "maxKontext": vram.MAX_KONTEXT},
        })

    def _nutzung(self):
        """Slot-Auslastung: Momentaufnahme plus Rueckblick aus den Logs."""
        try:
            zustand = dockerctl.status(mit_statistik=False)
            slots = int(zustand["einstellungen"].get("OLLAMA_NUM_PARALLEL")
                        or config.STANDARD_PARALLEL)
            logtext = dockerctl.logs(config.LOG_ZEILEN)
        except dockerctl.DockerFehler as fehler:
            self._json({"ok": False, "fehler": str(fehler)}, 200)
            return
        except (KeyError, ValueError):
            zustand = {"einstellungen": {}}
            slots = config.STANDARD_PARALLEL
            logtext = ""

        ergebnis = nutzung.auswerten(logtext, slots)
        ergebnis["live"] = self._live_slots(zustand, slots)
        self._json(ergebnis)

    def _live_slots(self, zustand, slots):
        """Zaehlt die gerade offenen Verbindungen zu Ollama.

        Das Zugriffslog kennt nur abgeschlossene Anfragen. Fuer den Blick auf
        das Jetzt liest das Portal daher /proc/net/tcp im Ollama-Container.
        """
        host = zustand.get("einstellungen", {}).get("OLLAMA_HOST", "")
        port = 11434
        if ":" in host:
            try:
                port = int(host.rsplit(":", 1)[1])
            except ValueError:
                pass
        try:
            ausgabe = dockerctl.ausfuehren(
                ["cat", "/proc/net/tcp", "/proc/net/tcp6"])
        except dockerctl.DockerFehler as fehler:
            return {"ok": False, "fehler": str(fehler)}
        return nutzung.live(ausgabe, port, slots, ollama.eigene_adresse())

    # -- Schreibende Routen ----------------------------------------------
    def do_POST(self):
        pfad = urlparse(self.path).path.rstrip("/") or "/"
        try:
            rumpf = self._rumpf()
        except (ValueError, json.JSONDecodeError) as fehler:
            self._fehler(f"Ungueltiger Anfragerumpf: {fehler}")
            return

        if pfad == "/api/docker/aktion":
            self._docker_aktion(rumpf)
        elif pfad == "/api/docker/einstellungen":
            self._einstellungen(rumpf)
        elif pfad == "/api/auth/einrichten":
            self._auth_einrichten(rumpf)
        elif pfad == "/api/auth/anmelden":
            self._auth_anmelden(rumpf)
        elif pfad == "/api/auth/abmelden":
            auth.abmelden(self._sitzung())
            self._json({"ok": True}, cookie=("", 0))
        elif pfad == "/api/auth/passwort":
            self._auth_passwort(rumpf)
        else:
            self._fehler("Unbekannter Endpunkt", 404)

    def _auth_einrichten(self, rumpf):
        try:
            auth.einrichten(rumpf.get("passwort", ""))
        except ValueError as fehler:
            self._fehler(str(fehler))
            return
        # Nach der Ersteinrichtung direkt angemeldet sein.
        token = auth.anmelden(rumpf.get("passwort", ""), self._adresse())
        self._json({"ok": True}, cookie=(token, config.SITZUNGSDAUER))

    def _auth_anmelden(self, rumpf):
        try:
            token = auth.anmelden(rumpf.get("passwort", ""), self._adresse())
        except PermissionError as fehler:
            self._fehler(str(fehler), 401)
            return
        self._json({"ok": True}, cookie=(token, config.SITZUNGSDAUER))

    def _auth_passwort(self, rumpf):
        if not self._angemeldet():
            self._fehler("Nicht angemeldet.", 401)
            return
        try:
            auth.passwort_aendern(rumpf.get("alt", ""), rumpf.get("neu", ""))
        except ValueError as fehler:
            self._fehler(str(fehler))
            return
        # Das Aendern beendet alle Sitzungen - auch die eigene.
        self._json({"ok": True, "hinweis": "Bitte neu anmelden."},
                   cookie=("", 0))

    def _docker_aktion(self, rumpf):
        if not self._darf_schreiben():
            return
        name = rumpf.get("aktion", "")
        try:
            self._json(dockerctl.aktion(name))
        except dockerctl.DockerFehler as fehler:
            self._fehler(str(fehler), 502)

    def _einstellungen(self, rumpf):
        if not self._darf_schreiben():
            return
        try:
            parallel = int(rumpf.get("parallel"))
            kontext = int(rumpf.get("kontext"))
        except (TypeError, ValueError):
            self._fehler("Nutzeranzahl und Kontext muessen Zahlen sein.")
            return
        kv_typ = rumpf.get("kv", "f16")
        meldung = vram.pruefe_eingaben(parallel, kontext, kv_typ)
        if meldung:
            self._fehler(meldung)
            return

        aenderungen = {
            "OLLAMA_NUM_PARALLEL": parallel,
            "OLLAMA_CONTEXT_LENGTH": kontext,
            "OLLAMA_KV_CACHE_TYPE": kv_typ,
        }
        try:
            ergebnis = dockerctl.einstellungen_uebernehmen(aenderungen)
        except dockerctl.DockerFehler as fehler:
            self._fehler(str(fehler), 502)
            return
        ergebnis["uebernommen"] = {k: str(v) for k, v in aenderungen.items()}
        self._json(ergebnis)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    server = Server((config.HOST, config.PORT), Handler)
    print(f"Portal laeuft auf http://{config.HOST}:{config.PORT}", flush=True)
    print(f"Ollama-Backend: {config.OLLAMA_URL}", flush=True)
    print(f"Ollama-Container: {config.CONTAINER_NAME} "
          f"(Steuerung {'aktiv' if config.DOCKER_STEUERUNG else 'deaktiviert'})",
          flush=True)
    if auth.per_umgebung():
        print("Passwort per PORTAL_PASSWORT vorgegeben", flush=True)
    elif auth.eingerichtet():
        print("Passwort ist eingerichtet", flush=True)
    else:
        print("Noch kein Passwort gesetzt - wird beim ersten Aufruf von "
              "/betrieb abgefragt", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Beende Portal", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
