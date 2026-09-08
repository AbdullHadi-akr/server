"""Vorgeschalteter Proxy vor Ollama - zaehlt Anfragen je Modell mit.

Weder die Ollama-API noch das Zugriffslog verraten, welches Modell eine
gerade laufende Anfrage belegt. Wer den Verkehr durch das Portal leitet,
bekommt genau das: fuer jedes Modell die Zahl der laufenden Anfragen und
damit auch die Warteschlange.

Ueblicherweise haengt der Proxy am selben Port wie das Portal (5021): Was
keine Portal-Route ist und keine statische Datei, geht an Ollama weiter. Das
geht auf, weil sich die Pfade nicht ueberschneiden - das Portal benennt seine
Endpunkte deutsch (/api/nutzung, /api/verlauf, /api/geladen ...), Ollama
englisch (/api/chat, /api/tags, /api/ps ...). Wer neue Portal-Endpunkte
ergaenzt, muss diese Trennung wahren.

Fuer den Fall, dass eine strikte Trennung gewuenscht ist, kann der Proxy auch
auf einem eigenen Port lauschen: PROXY_PORT abweichend von PORT setzen.

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

from . import benutzer, config, dockerctl, reservierung

# Pfade, die tatsaechlich einen Slot belegen - nur die werden mitgezaehlt.
SLOT_PFADE = ("/api/chat", "/api/generate", "/v1/chat/completions",
              "/v1/completions", "/api/embed", "/api/embeddings")

# Verbindungsbezogene Kopfzeilen gehoeren nicht weitergereicht.
UEBERSPRINGEN = {"connection", "keep-alive", "proxy-authenticate",
                 "proxy-authorization", "te", "trailer", "transfer-encoding",
                 "upgrade", "host", "content-length"}

# Zusaetzlich in der Anfrage: Der Zugangsschluessel gilt dem Portal, nicht
# Ollama - er hat dort nichts zu suchen.
UEBERSPRINGEN_ANFRAGE = UEBERSPRINGEN | {"authorization", "x-api-key"}

# Diese Pfade bleiben ohne Schluessel erreichbar: VS Code fragt damit die
# Modelle ab, und die Erreichbarkeitspruefung soll ohne Konto funktionieren.
OFFENE_PFADE = ("/api/version", "/api/tags", "/v1/models")

_schloss = threading.Lock()
_aktive = {}                      # laufende Nummer -> {modell, start, pfad}
_zaehler = itertools.count(1)
_gesamt = {"anfragen": 0, "fehler": 0, "ohneToken": 0, "abgewiesen": 0}
_laeuft = False


def _anmelden(modell, pfad, benutzername=""):
    nummer = next(_zaehler)
    with _schloss:
        _aktive[nummer] = {"modell": modell, "start": time.time(), "pfad": pfad,
                           "benutzer": benutzername or "(ohne Token)"}
        _gesamt["anfragen"] += 1
        if not benutzername:
            _gesamt["ohneToken"] += 1
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

    je_benutzer = {}
    for eintrag in laufend:
        name = eintrag.get("benutzer") or "(ohne Token)"
        je_benutzer[name] = je_benutzer.get(name, 0) + 1

    return {
        "ok": True,
        "aktiv": bool(_laeuft),
        "port": config.PROXY_PORT,
        "gesamtAktiv": len(laufend),
        "modelle": modelle,
        "benutzer": [{"name": n, "aktiv": a} for n, a in
                     sorted(je_benutzer.items())],
        "tokenPflicht": config.TOKEN_PFLICHT,
        "seitStart": gesamt,
    }


def _schluessel_aus(handler):
    """Liest den Zugangsschluessel aus der Anfrage."""
    kopf = handler.headers.get("Authorization") or ""
    if kopf.lower().startswith("bearer "):
        return kopf[7:].strip()
    return (handler.headers.get("X-Api-Key") or "").strip()


def anmeldung_pruefen(handler, pfad):
    """Bestimmt den Benutzer zur Anfrage.

    Liefert (benutzername, fehlermeldung). Ist die Meldung gesetzt, wurde die
    Anfrage abgewiesen. Im Duldungsmodus (TOKEN_PFLICHT=false) laufen Anfragen
    ohne Schluessel weiter durch und werden nur gezaehlt - so bricht bei der
    Umstellung niemandem der Chat weg.
    """
    if any(pfad.startswith(p) for p in OFFENE_PFADE):
        return "", None

    schluessel = _schluessel_aus(handler)
    if schluessel:
        konto = benutzer.finde_nach_token(schluessel)
        if konto:
            return konto["name"], None
        return "", ("Der Zugangsschluessel ist unbekannt oder das Konto ist "
                    "gesperrt. Einen neuen Schluessel gibt es im Portal unter "
                    "/konto.")

    if config.TOKEN_PFLICHT:
        return "", ("Es fehlt der Zugangsschluessel. In VS Code unter "
                    "'Chat: Manage Language Models' beim Anbieter den "
                    "persoenlichen Schluessel aus dem Portal (/konto) "
                    "hinterlegen.")
    return "", None


# Die Slot-Zahl kommt aus dem Container und aendert sich selten - einmal je
# Minute nachsehen genuegt.
_slots_cache = {"zeit": 0.0, "wert": None}


def slots_je_modell():
    if _slots_cache["wert"] is not None and \
            time.monotonic() - _slots_cache["zeit"] < 60:
        return _slots_cache["wert"]
    wert = config.STANDARD_PARALLEL
    try:
        umgebung = dockerctl.status(mit_statistik=False)["einstellungen"]
        wert = int(umgebung.get("OLLAMA_NUM_PARALLEL") or wert)
    except (dockerctl.DockerFehler, KeyError, ValueError, TypeError):
        pass
    _slots_cache.update({"zeit": time.monotonic(), "wert": wert})
    return wert


def reservierung_pruefen(benutzername, modell):
    """Darf diese Anfrage jetzt laufen?

    Waehrend einer Reservierung duerfen andere nur die nicht reservierten
    Slots belegen. Gerechnet wird gegen die Anfragen, die gerade wirklich
    laufen - so bremst die Regel nur, wenn es eng wird.
    """
    if not modell:
        return None
    reserviert = reservierung.je_modell(modell)
    if not reserviert:
        return None

    parallel = slots_je_modell()
    name = benutzername or "(ohne Token)"
    eigene = reserviert.get(name, {}).get("slots", 0)
    reserviert_gesamt = sum(g["slots"] for g in reserviert.values())
    frei_fuer_alle = max(0, parallel - reserviert_gesamt)

    with _schloss:
        laufend = {}
        for eintrag in _aktive.values():
            if eintrag["modell"] == modell:
                wer = eintrag.get("benutzer") or "(ohne Token)"
                laufend[wer] = laufend.get(wer, 0) + 1

    # Was andere ueber ihre eigene Reservierung hinaus belegen, geht vom
    # gemeinsamen Rest ab.
    ueberzug = sum(max(0, anzahl - reserviert.get(wer, {}).get("slots", 0))
                   for wer, anzahl in laufend.items() if wer != name)
    erlaubt = eigene + max(0, frei_fuer_alle - ueberzug)

    if laufend.get(name, 0) < erlaubt:
        return None

    halter = sorted((wer, g) for wer, g in reserviert.items() if wer != name)
    wer_text = ", ".join(
        f"{wer} ({g['slots']} Slots bis "
        f"{time.strftime('%H:%M', time.localtime(g['ende']))})"
        for wer, g in halter) or "andere Nutzer"
    return (f"Fuer {modell} sind gerade Slots reserviert: {wer_text}. "
            f"Von {parallel} Slots stehen dir zurzeit {erlaubt} zu. Bitte "
            "spaeter erneut versuchen oder im Portal selbst reservieren.")


def _modell_aus(rumpf):
    """Liest den Modellnamen aus dem Anfragerumpf."""
    if not rumpf:
        return ""
    try:
        daten = json.loads(rumpf.decode("utf-8", "replace"))
    except (json.JSONDecodeError, AttributeError):
        return ""
    return daten.get("model") or daten.get("name") or ""


def rumpf_lesen(handler):
    """Liest den Anfragerumpf, auch wenn er gestueckelt ankommt."""
    if (handler.headers.get("Transfer-Encoding") or "").lower() == "chunked":
        teile = []
        while True:
            zeile = handler.rfile.readline().strip()
            laenge = int(zeile.split(b";")[0] or b"0", 16)
            if laenge == 0:
                handler.rfile.readline()
                break
            teile.append(handler.rfile.read(laenge))
            handler.rfile.read(2)
        return b"".join(teile)
    laenge = int(handler.headers.get("Content-Length") or 0)
    return handler.rfile.read(laenge) if laenge else b""


def durchreichen(handler, rumpf=None):
    """Reicht die Anfrage an Ollama weiter und die Antwort ungepuffert zurueck.

    Wird von beiden Wegen genutzt: vom eigenen Proxy-Port und - im Regelfall -
    vom Portal-Server, wenn eine Anfrage keine seiner eigenen Routen trifft.
    """
    if rumpf is None:
        rumpf = rumpf_lesen(handler)
    pfad = urllib.parse.urlsplit(handler.path).path

    benutzername, abweisung = anmeldung_pruefen(handler, pfad)
    if abweisung:
        with _schloss:
            _gesamt["abgewiesen"] += 1
        _antwort_senden(handler, 401, {"error": abweisung})
        return

    zaehlen = any(pfad.startswith(p) for p in SLOT_PFADE)
    modell = _modell_aus(rumpf) if zaehlen else ""

    if zaehlen:
        gesperrt = reservierung_pruefen(benutzername, modell)
        if gesperrt:
            with _schloss:
                _gesamt["abgewiesen"] += 1
            _antwort_senden(handler, 429, {"error": gesperrt})
            return

    nummer = _anmelden(modell, pfad, benutzername) if zaehlen else None

    ziel = urllib.parse.urlsplit(config.OLLAMA_URL)
    kopfzeilen = {name: wert for name, wert in handler.headers.items()
                  if name.lower() not in UEBERSPRINGEN_ANFRAGE}
    kopfzeilen["Host"] = ziel.netloc
    if rumpf:
        kopfzeilen["Content-Length"] = str(len(rumpf))

    verbindung = None
    fehlerhaft = False
    try:
        # Kein Zeitlimit auf der Antwort: Generierungen dauern lange.
        verbindung = http.client.HTTPConnection(
            ziel.hostname, ziel.port or 80, timeout=config.PROXY_TIMEOUT)
        verbindung.request(handler.command, handler.path, body=rumpf or None,
                           headers=kopfzeilen)
        antwort = verbindung.getresponse()
        fehlerhaft = antwort.status >= 400
        _antwort_durchreichen(handler, antwort)
    except Exception as fehler:
        fehlerhaft = True
        _fehler_melden(handler, fehler)
    finally:
        if verbindung is not None:
            try:
                verbindung.close()
            except Exception:
                pass
        if nummer is not None:
            _abmelden(nummer, fehlerhaft)


def _antwort_durchreichen(handler, antwort):
    laenge = antwort.getheader("Content-Length")
    handler.send_response(antwort.status, antwort.reason)
    for name, wert in antwort.getheaders():
        if name.lower() not in UEBERSPRINGEN:
            handler.send_header(name, wert)
    if laenge is None:
        # Ohne bekannte Laenge selbst stueckeln - so geht jedes Stueck sofort
        # raus, statt bis zum Ende gesammelt zu werden.
        handler.send_header("Transfer-Encoding", "chunked")
    else:
        # Content-Length steht in UEBERSPRINGEN und wurde oben ausgelassen -
        # ohne sie wartet der Client ewig auf das Ende der Antwort.
        handler.send_header("Content-Length", laenge)
    handler.end_headers()

    if handler.command == "HEAD":
        return
    while True:
        # read1() statt read(): read() wartet, bis die angeforderte Menge voll
        # ist, und wuerde den Strom damit anhalten, bis die Antwort fertig ist.
        stueck = antwort.read1(4096)
        if not stueck:
            break
        if laenge is None:
            handler.wfile.write(f"{len(stueck):X}\r\n".encode() + stueck + b"\r\n")
        else:
            handler.wfile.write(stueck)
        handler.wfile.flush()
    if laenge is None:
        handler.wfile.write(b"0\r\n\r\n")
        handler.wfile.flush()


def _antwort_senden(handler, status, daten):
    """Kurze JSON-Antwort - die Meldung zeigt VS Code dem Nutzer an."""
    meldung = json.dumps(daten).encode("utf-8")
    try:
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(meldung)))
        handler.end_headers()
        handler.wfile.write(meldung)
    except OSError:
        pass  # Client ist schon weg


def _fehler_melden(handler, fehler):
    _antwort_senden(handler, 502,
                    {"error": f"Portal-Proxy erreicht Ollama nicht: {fehler}"})


class _Handler(BaseHTTPRequestHandler):
    server_version = "ModellPortalProxy/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # Ollama protokolliert selbst; doppelte Zeilen bringen nichts.

    def _weiterleiten(self):
        durchreichen(self)

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_PATCH = _weiterleiten


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def am_portal_port():
    """True, wenn der Proxy am Port des Portals haengt (kein zweiter Server)."""
    return config.PROXY_PORT == config.PORT


def starten():
    """Startet den Proxy - als eigener Server nur bei abweichendem Port."""
    global _laeuft
    if _laeuft or not config.PROXY_AKTIV:
        return False
    if am_portal_port():
        # Der Portal-Server reicht selbst durch; ein zweiter Listener auf
        # demselben Port waere gar nicht moeglich.
        _laeuft = True
        return True
    server = _Server((config.HOST, config.PROXY_PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _laeuft = True
    return True
