"""HTTP-Server des Portals: statische Seiten, Diagnose- und Betriebs-API."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import (auth, benutzer, config, dockerctl, gpu, modelle, nutzung,
               ollama, proxy, pruefung, reservierung, verlauf, vram)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}

# Groesster akzeptierter Anfragerumpf der eigenen Endpunkte - die Nutzlasten
# hier sind winzig. Weitergereichte Modell-Anfragen sind davon nicht betroffen.
MAX_RUMPF = 64 * 1024

# Eigene POST-Endpunkte. Alles andere geht an Ollama weiter, sofern der Proxy
# am Portal-Port haengt.
EIGENE_POST_ROUTEN = {
    "/api/docker/aktion", "/api/docker/einstellungen",
    "/api/modelle/laden", "/api/modelle/loeschen",
    "/api/auth/einrichten", "/api/auth/anmelden", "/api/auth/abmelden",
    "/api/auth/passwort",
    "/api/benutzer/anlegen", "/api/benutzer/aendern", "/api/benutzer/passwort",
    "/api/benutzer/token", "/api/benutzer/loeschen",
    "/api/konto/token",
    "/api/reservierungen/anlegen", "/api/reservierungen/loeschen",
}


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

    def _konto(self):
        """Die angemeldete Sitzung, oder None."""
        return auth.sitzung(self._sitzung())

    def _angemeldet(self):
        return self._konto() is not None

    def _adresse(self):
        return self.client_address[0] if self.client_address else "unbekannt"

    def _verlangt_anmeldung(self):
        """Fuer alles, was jeder angemeldete Benutzer darf."""
        if self._konto() is None:
            self._fehler("Nicht angemeldet.", 401)
            return None
        return self._konto()

    def _verlangt_admin(self):
        """Fuer alles, was den Server veraendert - nur fuer Administratoren."""
        eintrag = self._konto()
        if eintrag is None:
            self._fehler("Nicht angemeldet.", 401)
            return None
        if eintrag["rolle"] != benutzer.ADMIN:
            self._fehler("Diese Aktion ist Administratoren vorbehalten.", 403)
            return None
        return eintrag

    def _darf_schreiben(self):
        """Aendert den Ollama-Container - Admin und Steuerung freigeschaltet."""
        if self._verlangt_admin() is None:
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

    def _static_pfad(self, name):
        """Pfad der statischen Datei, oder None - schuetzt vor Pfad-Ausbruch."""
        pfad = os.path.join(STATIC_DIR, name)
        if not os.path.abspath(pfad).startswith(STATIC_DIR) or not os.path.isfile(pfad):
            return None
        return pfad

    def _unbekannt(self, name=""):
        """Weder Portal-Route noch Datei: an Ollama weiterreichen.

        So bedient das Portal unter demselben Port auch die Modell-Anfragen.
        Ist der Proxy aus, bleibt es bei 404.
        """
        if name and self._static_pfad(name):
            self._static(name)
            return
        if config.PROXY_AKTIV and proxy.am_portal_port():
            proxy.durchreichen(self)
            return
        self._send(404, "Nicht gefunden", "text/plain; charset=utf-8")

    def _static(self, name):
        pfad = self._static_pfad(name)
        # Pfad-Ausbruch verhindern.
        if pfad is None:
            self._send(404, "Nicht gefunden", "text/plain; charset=utf-8")
            return
        with open(pfad, "rb") as datei:
            inhalt = datei.read()
        endung = os.path.splitext(pfad)[1]
        self._send(200, inhalt, CONTENT_TYPES.get(endung, "application/octet-stream"))

    # -- Lesende Routen --------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_DELETE(self):
        self._unbekannt()   # Ollama loescht Modelle per DELETE /api/delete

    def do_PUT(self):
        self._unbekannt()

    def do_PATCH(self):
        self._unbekannt()

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
        elif pfad == "/verlauf":
            self._static("verlauf.html")
        elif pfad == "/benutzer":
            self._static("benutzer.html")
        elif pfad == "/konto":
            self._static("konto.html")
        elif pfad == "/anmelden":
            self._static("anmelden.html")
        elif pfad == "/anleitung":
            self._static("anleitung.html")
        elif pfad == "/reservierungen":
            self._static("reservierungen.html")
        elif pfad == "/healthz":
            # Schlanker Endpunkt fuer den Docker-Healthcheck.
            self._json({"status": "ok", "version": config.VERSION,
                        "seiten": ["/", "/uebersicht", "/verlauf", "/anleitung",
                                   "/anmelden",
                                   "/reservierungen", "/betrieb", "/benutzer",
                                   "/konto"],
                        "proxy": config.PROXY_PORT if config.PROXY_AKTIV else None})
        elif pfad == "/api/modelle":
            self._json({
                "ollamaUrl": config.OLLAMA_URL,
                "publicUrl": config.PUBLIC_OLLAMA_URL,
                "vendor": config.VENDOR_NAME,
                "version": config.VERSION,
                "altUrl": config.ALT_OLLAMA_URL,
                "proxyAktiv": config.PROXY_AKTIV,
                "ueberProxy": f":{config.PROXY_PORT}" in config.PUBLIC_OLLAMA_URL,
                "tokenPflicht": config.TOKEN_PFLICHT,
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
        elif pfad == "/api/modelle/liste":
            self._json(modelle.liste())
        elif pfad == "/api/modelle/fortschritt":
            self._json({"ok": True, **modelle.fortschritt()})
        elif pfad == "/api/modelle/details":
            self._json(modelle.details((parameter.get("name") or [""])[0]))
        elif pfad == "/api/aktiv":
            self._aktiv()
        elif pfad == "/api/verlauf":
            self._json(verlauf.lesen((parameter.get("zeitraum") or ["24h"])[0]))
        elif pfad == "/api/gpu":
            self._json({"ok": True, **gpu.werte()})
        elif pfad == "/api/pruefung":
            self._pruefung()
        elif pfad == "/api/auth/status":
            eintrag = self._konto()
            self._json({
                "ok": True,
                "angemeldet": eintrag is not None,
                "benutzer": ({"name": eintrag["name"], "rolle": eintrag["rolle"]}
                             if eintrag else None),
                "istAdmin": bool(eintrag and eintrag["rolle"] == benutzer.ADMIN),
                "steuerungAktiv": config.DOCKER_STEUERUNG,
                **auth.zustand()})
        elif pfad == "/api/benutzer":
            self._benutzer_liste()
        elif pfad == "/api/konto":
            self._konto_lesen()
        elif pfad == "/api/reservierungen":
            self._reservierungen(parameter)
        else:
            self._unbekannt(pfad.lstrip("/"))

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
        # Gegen den tatsaechlich vorhandenen Speicher rechnen, wenn
        # nvidia-smi erreichbar ist - sonst gegen den konfigurierten Wert.
        gpu_daten = gpu.werte()
        vram_gib = gpu_daten["vramGib"]
        gpu_name = (", ".join(g["name"] for g in gpu_daten["gpus"])
                    if gpu_daten.get("gemessen") else config.GPU_NAME)
        self._json({
            "ok": True,
            "gpu": gpu_name,
            "gemessen": bool(gpu_daten.get("gemessen")),
            **vram.uebersicht(parallel, kontext, kv_typ,
                              vram_gib, gleichzeitig),
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

        # OLLAMA_NUM_PARALLEL gilt je geladenem Modell: Ollama haelt fuer
        # jedes Modell einen eigenen Satz Slots vor. Die Gesamtkapazitaet ist
        # also das Vielfache der Anzahl geladener Modelle.
        geladen = ollama.geladene_modelle()
        anzahl_modelle = len(geladen.get("modelle", [])) if geladen.get("ok") else 0
        # Ist /api/ps gerade nicht erreichbar, verraet der Proxy trotzdem, fuer
        # wie viele verschiedene Modelle Anfragen laufen - die untere Schranke
        # der geladenen Modelle.
        im_proxy = len(proxy.zustand(slots)["modelle"])
        slots_gesamt = slots * max(1, anzahl_modelle, im_proxy)

        ergebnis = nutzung.auswerten(logtext, slots_gesamt)
        ergebnis["slotsJeModell"] = slots
        ergebnis["modelleGeladen"] = anzahl_modelle
        ergebnis["live"] = self._live_slots(zustand, slots_gesamt)
        ergebnis["live"]["slotsJeModell"] = slots
        ergebnis["live"]["modelleGeladen"] = anzahl_modelle
        self._json(ergebnis)

    def _aktiv(self):
        """Laufende Anfragen je Modell - nur im Proxy-Modus belastbar."""
        parallel = config.STANDARD_PARALLEL
        try:
            umgebung = dockerctl.status(mit_statistik=False)["einstellungen"]
            parallel = int(umgebung.get("OLLAMA_NUM_PARALLEL") or parallel)
        except (dockerctl.DockerFehler, KeyError, ValueError, TypeError):
            pass
        self._json(proxy.zustand(parallel))

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
        parallel = 0
        try:
            parallel = int(zustand.get("einstellungen", {})
                           .get("OLLAMA_NUM_PARALLEL") or config.STANDARD_PARALLEL)
        except (ValueError, TypeError):
            parallel = config.STANDARD_PARALLEL

        # Laeuft der Verkehr durch den Proxy, sind dessen Zahlen exakt und
        # zudem je Modell aufgeschluesselt - die Verbindungszaehlung ist dann
        # nur noch Rueckfallebene.
        proxy_daten = proxy.zustand(parallel)
        if proxy_daten["aktiv"] and proxy_daten["gesamtAktiv"]:
            return {
                "ok": True,
                "quelle": "proxy",
                "aktiv": proxy_daten["gesamtAktiv"],
                "slots": slots,
                "frei": max(0, slots - proxy_daten["gesamtAktiv"]),
                "ueberbucht": proxy_daten["gesamtAktiv"] > slots,
                "auslastung": (round(proxy_daten["gesamtAktiv"] / slots * 100, 1)
                               if slots else 0.0),
                "eigene": 0,
                "port": config.PROXY_PORT,
                "jeModell": proxy_daten["modelle"],
                "jeBenutzer": proxy_daten["benutzer"],
                "ohneToken": proxy_daten["seitStart"].get("ohneToken", 0),
                "tokenPflicht": proxy_daten["tokenPflicht"],
            }

        try:
            ausgabe = dockerctl.ausfuehren(
                ["cat", "/proc/net/tcp", "/proc/net/tcp6"])
        except dockerctl.DockerFehler as fehler:
            return {"ok": False, "fehler": str(fehler)}
        ergebnis = nutzung.live(ausgabe, port, slots, ollama.eigene_adresse())
        ergebnis["quelle"] = "verbindungen"
        if proxy_daten["aktiv"]:
            ergebnis["jeModell"] = proxy_daten["modelle"]
        return ergebnis

    def _pruefung(self):
        """Sammelt Hinweise auf unstimmige Einstellungen."""
        try:
            zustand = dockerctl.status(mit_statistik=False)
        except dockerctl.DockerFehler:
            # Ohne Docker-Zugriff bleiben die Pruefungen uebrig, die allein
            # aus der Portal-Konfiguration folgen.
            zustand = {"einstellungen": {}}
        self._json(pruefung.hinweise(zustand, ollama.geladene_modelle(),
                                     gpu.werte()))

    def _benutzer_liste(self):
        if self._verlangt_admin() is None:
            return
        self._json({"ok": True, "benutzer": benutzer.liste(),
                    "rollen": list(benutzer.ROLLEN)})

    def _konto_lesen(self):
        eintrag = self._verlangt_anmeldung()
        if eintrag is None:
            return
        self._json({"ok": True, "benutzer": benutzer.finde(eintrag["benutzerId"])})

    def _reservierungen(self, parameter):
        """Reservierungen eines Tages - fuer alle sichtbar, auch ohne Anmeldung."""
        eintrag = self._konto()
        try:
            daten = reservierung.fuer_tag((parameter.get("tag") or [""])[0] or None)
        except ValueError as fehler:
            self._fehler(str(fehler))
            return
        daten.update({
            "ok": True,
            "modelle": [{"id": m["id"], "name": m["name"]} for m in config.MODELS],
            "slots": proxy.slots_je_modell(),
            "maxStunden": config.RESERVIERUNG_MAX_STUNDEN,
            "minFrei": config.RESERVIERUNG_MIN_FREI,
            "angemeldet": eintrag is not None,
            "istAdmin": bool(eintrag and eintrag["rolle"] == benutzer.ADMIN),
            "eigenerName": eintrag["name"] if eintrag else "",
            "eigene": (reservierung.eigene(eintrag["benutzerId"])
                       if eintrag else []),
        })
        self._json(daten)

    # -- Schreibende Routen ----------------------------------------------
    def do_POST(self):
        pfad = urlparse(self.path).path.rstrip("/") or "/"
        if pfad not in EIGENE_POST_ROUTEN:
            # Modell-Anfragen (z. B. /v1/chat/completions) gehen an Ollama.
            self._unbekannt()
            return
        try:
            rumpf = self._rumpf()
        except (ValueError, json.JSONDecodeError) as fehler:
            self._fehler(f"Ungueltiger Anfragerumpf: {fehler}")
            return

        if pfad == "/api/docker/aktion":
            self._docker_aktion(rumpf)
        elif pfad == "/api/docker/einstellungen":
            self._einstellungen(rumpf)
        elif pfad == "/api/modelle/laden":
            self._modell_laden(rumpf)
        elif pfad == "/api/modelle/loeschen":
            self._modell_loeschen(rumpf)
        elif pfad == "/api/benutzer/anlegen":
            self._benutzer_anlegen(rumpf)
        elif pfad == "/api/benutzer/aendern":
            self._benutzer_aendern(rumpf)
        elif pfad == "/api/benutzer/passwort":
            self._benutzer_passwort(rumpf)
        elif pfad == "/api/benutzer/token":
            self._benutzer_token(rumpf)
        elif pfad == "/api/benutzer/loeschen":
            self._benutzer_loeschen(rumpf)
        elif pfad == "/api/konto/token":
            self._konto_token()
        elif pfad == "/api/reservierungen/anlegen":
            self._reservierung_anlegen(rumpf)
        elif pfad == "/api/reservierungen/loeschen":
            self._reservierung_loeschen(rumpf)
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

    def _modell_laden(self, rumpf):
        if not self._darf_schreiben():
            return
        try:
            self._json(modelle.laden(str(rumpf.get("name", "")).strip()))
        except ValueError as fehler:
            self._fehler(str(fehler))

    def _modell_loeschen(self, rumpf):
        if not self._darf_schreiben():
            return
        try:
            self._json(modelle.loeschen(str(rumpf.get("name", "")).strip(),
                                        bool(rumpf.get("bestaetigt"))))
        except ValueError as fehler:
            self._fehler(str(fehler))

    def _auth_einrichten(self, rumpf):
        name = str(rumpf.get("name", "")).strip() or "admin"
        passwort = rumpf.get("passwort", "")
        try:
            ergebnis = auth.einrichten(name, passwort)
        except ValueError as fehler:
            self._fehler(str(fehler))
            return
        # Nach der Ersteinrichtung direkt angemeldet sein.
        token, _ = auth.anmelden(name, passwort, self._adresse())
        self._json({"ok": True, "benutzer": ergebnis["benutzer"],
                    "token": ergebnis["token"]},
                   cookie=(token, config.SITZUNGSDAUER))

    def _auth_anmelden(self, rumpf):
        try:
            token, konto = auth.anmelden(rumpf.get("name", ""),
                                         rumpf.get("passwort", ""),
                                         self._adresse())
        except PermissionError as fehler:
            self._fehler(str(fehler), 401)
            return
        self._json({"ok": True, "benutzer": {"name": konto["name"],
                                             "rolle": konto["rolle"]}},
                   cookie=(token, config.SITZUNGSDAUER))

    def _auth_passwort(self, rumpf):
        """Aendert das eigene Passwort."""
        eintrag = self._verlangt_anmeldung()
        if eintrag is None:
            return
        try:
            benutzer.passwort_aendern(eintrag["benutzerId"],
                                      rumpf.get("alt", ""), rumpf.get("neu", ""))
        except ValueError as fehler:
            self._fehler(str(fehler))
            return
        # Der Wechsel beendet alle eigenen Sitzungen.
        auth.sitzungen_beenden(eintrag["benutzerId"])
        self._json({"ok": True, "hinweis": "Bitte neu anmelden."},
                   cookie=("", 0))

    # -- Benutzerverwaltung (Admin) --------------------------------------
    def _benutzer_anlegen(self, rumpf):
        if self._verlangt_admin() is None:
            return
        try:
            ergebnis = benutzer.anlegen(rumpf.get("name", ""),
                                        rumpf.get("passwort", ""),
                                        rumpf.get("rolle", benutzer.NUTZER))
        except ValueError as fehler:
            self._fehler(str(fehler))
            return
        # Der Token ist hier zum einzigen Mal im Klartext zu sehen.
        self._json({"ok": True, **ergebnis})

    def _benutzer_aendern(self, rumpf):
        if self._verlangt_admin() is None:
            return
        try:
            konto = benutzer.aendern(int(rumpf.get("id", 0)),
                                     rolle=rumpf.get("rolle"),
                                     aktiv=rumpf.get("aktiv"))
        except (ValueError, TypeError) as fehler:
            self._fehler(str(fehler))
            return
        # Gesperrte oder herabgestufte Konten verlieren ihre offenen Sitzungen.
        auth.sitzungen_beenden(konto["id"])
        self._json({"ok": True, "benutzer": konto})

    def _benutzer_passwort(self, rumpf):
        if self._verlangt_admin() is None:
            return
        try:
            benutzer_id = int(rumpf.get("id", 0))
            benutzer.passwort_setzen(benutzer_id, rumpf.get("passwort", ""))
        except (ValueError, TypeError) as fehler:
            self._fehler(str(fehler))
            return
        auth.sitzungen_beenden(benutzer_id)
        self._json({"ok": True})

    def _benutzer_token(self, rumpf):
        if self._verlangt_admin() is None:
            return
        try:
            token = benutzer.token_erneuern(int(rumpf.get("id", 0)))
        except (ValueError, TypeError) as fehler:
            self._fehler(str(fehler))
            return
        self._json({"ok": True, "token": token})

    def _benutzer_loeschen(self, rumpf):
        eintrag = self._verlangt_admin()
        if eintrag is None:
            return
        try:
            benutzer_id = int(rumpf.get("id", 0))
        except (ValueError, TypeError):
            self._fehler("Unbekannter Benutzer.")
            return
        if benutzer_id == eintrag["benutzerId"]:
            self._fehler("Das eigene Konto laesst sich nicht loeschen.")
            return
        try:
            benutzer.loeschen(benutzer_id)
        except ValueError as fehler:
            self._fehler(str(fehler))
            return
        auth.sitzungen_beenden(benutzer_id)
        self._json({"ok": True})

    def _reservierung_anlegen(self, rumpf):
        eintrag = self._verlangt_anmeldung()
        if eintrag is None:
            return
        try:
            neu = reservierung.anlegen(
                eintrag["benutzerId"], eintrag["rolle"] == benutzer.ADMIN,
                rumpf.get("modell", ""), rumpf.get("start", ""),
                rumpf.get("ende", ""), rumpf.get("slots", 1),
                rumpf.get("notiz", ""), proxy.slots_je_modell())
        except ValueError as fehler:
            self._fehler(str(fehler))
            return
        self._json({"ok": True, "reservierung": neu})

    def _reservierung_loeschen(self, rumpf):
        eintrag = self._verlangt_anmeldung()
        if eintrag is None:
            return
        try:
            reservierung.loeschen(int(rumpf.get("id", 0)), eintrag["benutzerId"],
                                  eintrag["rolle"] == benutzer.ADMIN)
        except (ValueError, TypeError) as fehler:
            self._fehler(str(fehler))
            return
        self._json({"ok": True})

    def _konto_token(self):
        """Erneuert den eigenen Zugangsschluessel."""
        eintrag = self._verlangt_anmeldung()
        if eintrag is None:
            return
        self._json({"ok": True,
                    "token": benutzer.token_erneuern(eintrag["benutzerId"])})

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


def _messwerte(letzte_anfrage):
    """Liefert dem Verlauf einen Satz Rohdaten - fehlertolerant.

    Faellt eine Quelle aus (kein Docker-Socket, Ollama nicht erreichbar), wird
    der Messpunkt trotzdem geschrieben; die fehlenden Felder bleiben null.
    """
    werte = {"letzteAnfrage": letzte_anfrage}

    parallel = config.STANDARD_PARALLEL
    umgebung = {}
    try:
        zustand = dockerctl.status(mit_statistik=False)
        umgebung = zustand.get("einstellungen", {})
        parallel = int(umgebung.get("OLLAMA_NUM_PARALLEL") or parallel)
    except (dockerctl.DockerFehler, ValueError, TypeError):
        zustand = None

    geladen = ollama.geladene_modelle()
    anzahl = len(geladen.get("modelle", [])) if geladen.get("ok") else 0

    # Im Proxy-Modus sind die laufenden Anfragen exakt bekannt - und je Modell.
    proxy_daten = proxy.zustand(parallel)
    werte["jeModell"] = proxy_daten["modelle"]
    if proxy_daten["aktiv"] and proxy_daten["gesamtAktiv"]:
        werte["aktiv"] = proxy_daten["gesamtAktiv"]

    werte["modelle"] = anzahl
    werte["slots"] = parallel * max(1, anzahl, len(proxy_daten["modelle"]))

    gpu_daten = gpu.werte()
    if gpu_daten.get("gemessen"):
        werte["vramBelegt"] = gpu_daten.get("vramBelegtGib", 0.0)
        werte["vramGesamt"] = gpu_daten.get("vramGib", 0.0)
        werte["gpuLast"] = (gpu_daten["gpus"][0].get("auslastung") or 0.0
                            if gpu_daten["gpus"] else 0.0)
    else:
        werte["vramBelegt"] = geladen.get("summeGib", 0.0) if geladen.get("ok") else 0.0
        werte["vramGesamt"] = config.GPU_VRAM_GIB

    if zustand is not None:
        try:
            port = 11434
            host = umgebung.get("OLLAMA_HOST", "")
            if ":" in host:
                port = int(host.rsplit(":", 1)[1])
            ausgabe = dockerctl.ausfuehren(["cat", "/proc/net/tcp", "/proc/net/tcp6"])
            live = nutzung.live(ausgabe, port, werte["slots"],
                                ollama.eigene_adresse())
            # Nur setzen, wenn der Proxy keine Zahl geliefert hat - seine ist
            # exakt, die Verbindungszaehlung nur eine Naeherung.
            werte.setdefault("aktiv", live["aktiv"])
        except (dockerctl.DockerFehler, ValueError):
            pass
        try:
            neue = nutzung.neue_anfragen(dockerctl.logs(config.LOG_ZEILEN),
                                         letzte_anfrage)
            werte.update({"anfragen": neue["anzahl"], "medianS": neue["medianSekunden"],
                          "fehler": neue["fehler"], "letzteAnfrage": neue["letzte"]})
        except dockerctl.DockerFehler:
            pass
    return werte


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _konten_vorbereiten():
    """Sorgt dafuer, dass es beim Start einen Admin gibt."""
    uebernommen = benutzer.uebernehme_altes_passwort()
    if uebernommen:
        print(f"Bisheriges Einzelpasswort uebernommen: Benutzer '{uebernommen}' "
              "mit der Rolle admin", flush=True)
    elif config.PORTAL_PASSWORT and not benutzer.eingerichtet():
        # Vorgabe per Umgebung: nuetzlich fuer automatisierte Installationen.
        try:
            benutzer.anlegen("admin", config.PORTAL_PASSWORT, benutzer.ADMIN)
            print("Admin 'admin' aus PORTAL_PASSWORT angelegt", flush=True)
        except ValueError as fehler:
            print(f"PORTAL_PASSWORT nicht verwendbar: {fehler}", flush=True)

    anzahl = benutzer.anzahl()
    if anzahl:
        print(f"{anzahl} Benutzerkonten", flush=True)
    else:
        print("Noch kein Konto. Der erste Aufruf von /betrieb legt den "
              "Administrator an", flush=True)


def main():
    server = Server((config.HOST, config.PORT), Handler)
    print(f"Portal laeuft auf http://{config.HOST}:{config.PORT}", flush=True)
    print(f"Ollama-Backend: {config.OLLAMA_URL}", flush=True)
    print(f"Ollama-Container: {config.CONTAINER_NAME} "
          f"(Steuerung {'aktiv' if config.DOCKER_STEUERUNG else 'deaktiviert'})",
          flush=True)
    _konten_vorbereiten()
    # Lange abgelaufene Reservierungen wegraeumen.
    try:
        reservierung.aufraeumen()
    except Exception as fehler:
        print(f"Reservierungen konnten nicht aufgeraeumt werden: {fehler}", flush=True)
    if proxy.starten():
        print(f"Proxy laeuft auf http://{config.HOST}:{config.PROXY_PORT} "
              f"-> {config.OLLAMA_URL}", flush=True)
    if verlauf.starten(_messwerte):
        print(f"Verlauf: Aufzeichnung alle {config.VERLAUF_TAKT} s, "
              f"Aufbewahrung {config.VERLAUF_TAGE} Tage", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Beende Portal", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
