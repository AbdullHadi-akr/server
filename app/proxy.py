"""Vorgeschalteter Proxy vor Ollama - zaehlt Anfragen je Modell mit.

Weder die Ollama-API noch das Zugriffslog verraten, welches Modell eine
gerade laufende Anfrage belegt. Wer den Verkehr durch das Portal leitet,
bekommt genau das: fuer jedes Modell die Zahl der laufenden Anfragen und
damit auch die Warteschlange.

Der Proxy lauscht auf einem eigenen Port. Ollamas /api/* wuerde sich sonst
mit den gleichnamigen Endpunkten des Portals ueberschneiden.

Wichtig ist das ungepufferte Durchreichen der Antwort: Kaeme sie erst am
Stueck beim Client an, wuerde der Chat in VS Code nicht mehr Wort fuer Wort
erscheinen.
"""

import http.client
import itertools
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config

# Pfade, die tatsaechlich einen Slot belegen - nur die werden mitgezaehlt.
SLOT_PFADE = ("/api/chat", "/api/generate", "/v1/chat/completions",
              "/v1/completions", "/api/embed", "/api/embeddings")

# Verbindungsbezogene Kopfzeilen gehoeren nicht weitergereicht.
UEBERSPRINGEN = {"connection", "keep-alive", "proxy-authenticate",
                 "proxy-authorization", "te", "trailer", "transfer-encoding",
                 "upgrade", "host", "content-length"}

_schloss = threading.Lock()
_aktive = {}                      # laufende Nummer -> {modell, start, pfad}
_zaehler = itertools.count(1)
_gesamt = {"anfragen": 0, "fehler": 0}
_laeuft = False


def _anmelden(modell, pfad):
    nummer = next(_zaehler)
    with _schloss:
        _aktive[nummer] = {"modell": modell, "start": time.time(), "pfad": pfad}
        _gesamt["anfragen"] += 1
    return nummer


def _abmelden(nummer, fehlerhaft=False):
    with _schloss:
        _aktive.pop(nummer, None)
        if fehlerhaft:
            _gesamt["fehler"] += 1


def zustand(slots_je_modell):
    """Laufende Anfragen je Modell, aufgeteilt in rechnend und wartend."""
    with _schloss:
        laufend = list(_aktive.values())
        gesamt = dict(_gesamt)

    je_modell = {}
    jetzt = time.time()
    for eintrag in laufend:
        name = eintrag["modell"] or "(unbekannt)"
        gruppe = je_modell.setdefault(name, {"modell": name, "aktiv": 0,
                                             "laengsteSekunden": 0.0})
        gruppe["aktiv"] += 1
        gruppe["laengsteSekunden"] = max(gruppe["laengsteSekunden"],
                                         round(jetzt - eintrag["start"], 1))

    modelle = []
    for gruppe in je_modell.values():
        # Ollama haelt je Modell OLLAMA_NUM_PARALLEL Slots vor; alles
        # darueber wartet in der Warteschlange.
        gruppe["rechnend"] = min(gruppe["aktiv"], slots_je_modell)
        gruppe["wartend"] = max(0, gruppe["aktiv"] - slots_je_modell)
        gruppe["slots"] = slots_je_modell
        modelle.append(gruppe)
    modelle.sort(key=lambda m: m["modell"])

    return {
        "ok": True,
        "aktiv": bool(_laeuft),
        "port": config.PROXY_PORT,
        "gesamtAktiv": len(laufend),
        "modelle": modelle,
        "seitStart": gesamt,
    }


def _modell_aus(rumpf):
    """Liest den Modellnamen aus dem Anfragerumpf."""
    if not rumpf:
        return ""
    try:
        daten = json.loads(rumpf.decode("utf-8", "replace"))
    except (json.JSONDecodeError, AttributeError):
        return ""
    return daten.get("model") or daten.get("name") or ""


class _Handler(BaseHTTPRequestHandler):
    server_version = "ModellPortalProxy/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # Ollama protokolliert selbst; doppelte Zeilen bringen nichts.

    def _rumpf_lesen(self):
        if (self.headers.get("Transfer-Encoding") or "").lower() == "chunked":
            teile = []
            while True:
                zeile = self.rfile.readline().strip()
                laenge = int(zeile.split(b";")[0] or b"0", 16)
                if laenge == 0:
                    self.rfile.readline()
                    break
                teile.append(self.rfile.read(laenge))
                self.rfile.read(2)
            return b"".join(teile)
        laenge = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(laenge) if laenge else b""

    def _weiterleiten(self):
        rumpf = self._rumpf_lesen()
        pfad = urllib.parse.urlsplit(self.path).path
        zaehlen = any(pfad.startswith(p) for p in SLOT_PFADE)
        nummer = _anmelden(_modell_aus(rumpf), pfad) if zaehlen else None

        ziel = urllib.parse.urlsplit(config.OLLAMA_URL)
        kopfzeilen = {name: wert for name, wert in self.headers.items()
                      if name.lower() not in UEBERSPRINGEN}
        kopfzeilen["Host"] = ziel.netloc
        if rumpf:
            kopfzeilen["Content-Length"] = str(len(rumpf))

        fehlerhaft = False
        try:
            # Kein Zeitlimit auf der Antwort: Generierungen dauern lange.
            verbindung = http.client.HTTPConnection(
                ziel.hostname, ziel.port or 80, timeout=config.PROXY_TIMEOUT)
            verbindung.request(self.command, self.path, body=rumpf or None,
                               headers=kopfzeilen)
            antwort = verbindung.getresponse()
            fehlerhaft = antwort.status >= 400
            self._antwort_durchreichen(antwort)
        except Exception as fehler:
            fehlerhaft = True
            self._fehler_melden(fehler)
        finally:
            try:
                verbindung.close()
            except Exception:
                pass
            if nummer is not None:
                _abmelden(nummer, fehlerhaft)

    def _antwort_durchreichen(self, antwort):
        laenge = antwort.getheader("Content-Length")
        self.send_response(antwort.status, antwort.reason)
        for name, wert in antwort.getheaders():
            if name.lower() not in UEBERSPRINGEN:
                self.send_header(name, wert)
        if laenge is None:
            # Ohne bekannte Laenge selbst stueckeln - so geht jedes Stueck
            # sofort raus, statt bis zum Ende gesammelt zu werden.
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        if self.command == "HEAD":
            return
        while True:
            # read1() statt read(): read() wartet, bis die angeforderte Menge
            # voll ist, und wuerde den Strom damit anhalten, bis die Antwort
            # fertig ist. read1() gibt zurueck, was gerade da ist.
            stueck = antwort.read1(4096)
            if not stueck:
                break
            if laenge is None:
                self.wfile.write(f"{len(stueck):X}\r\n".encode() + stueck + b"\r\n")
            else:
                self.wfile.write(stueck)
            self.wfile.flush()
        if laenge is None:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

    def _fehler_melden(self, fehler):
        meldung = json.dumps({
            "error": f"Portal-Proxy erreicht Ollama nicht: {fehler}",
        }).encode("utf-8")
        try:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(meldung)))
            self.end_headers()
            self.wfile.write(meldung)
        except OSError:
            pass  # Client ist schon weg

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_PATCH = _weiterleiten


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def starten():
    """Startet den Proxy in einem Hintergrund-Thread."""
    global _laeuft
    if _laeuft or not config.PROXY_AKTIV:
        return False
    server = _Server((config.HOST, config.PROXY_PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _laeuft = True
    return True
