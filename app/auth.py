"""Anmeldung und Sitzungen.

Die Konten selbst liegen in app/benutzer.py; hier geht es nur darum, wer
gerade angemeldet ist. Nach der Anmeldung erhaelt der Browser ein zufaelliges
Sitzungs-Token als HttpOnly-Cookie. Die Sitzungen liegen ausschliesslich im
Arbeitsspeicher und sind nach einem Neustart des Portals ungueltig.

Fuenf Fehlversuche sperren fuer eine Minute - gezaehlt wird sowohl je Adresse
als auch je Benutzername, damit weder das Durchprobieren vieler Passwoerter
von einer Stelle noch das Durchprobieren eines Kontos von vielen Stellen aus
lohnt.
"""

import secrets
import threading
import time

from . import benutzer, config

MAX_FEHLVERSUCHE = 5
SPERRDAUER = 60

_schloss = threading.Lock()
_sitzungen = {}       # Token -> {benutzerId, name, rolle, ablauf}
_fehlversuche = {}    # Schluessel (Adresse oder Name) -> [Anzahl, gesperrt_bis]


# ---------------------------------------------------------------- Zustand
def per_umgebung():
    """True, wenn ein Admin-Passwort fest per PORTAL_PASSWORT vorgegeben ist."""
    return bool(config.PORTAL_PASSWORT)


def eingerichtet():
    return benutzer.eingerichtet() or per_umgebung()


def schreibbar():
    """Prueft, ob das Datenverzeichnis beschreibbar ist."""
    import os
    try:
        os.makedirs(config.DATEN_DIR, exist_ok=True)
        return os.access(config.DATEN_DIR, os.W_OK)
    except OSError:
        return False


def zustand():
    return {
        "eingerichtet": eingerichtet(),
        "perUmgebung": per_umgebung(),
        "speicherbar": schreibbar(),
        "datenVerzeichnis": config.DATEN_DIR,
        "minLaenge": benutzer.MIN_LAENGE,
        "benutzerAnzahl": benutzer.anzahl(),
    }


# ------------------------------------------------------------ Einrichtung
def einrichten(name, passwort):
    """Legt beim ersten Aufruf den ersten Admin an."""
    if benutzer.eingerichtet():
        raise ValueError("Es gibt bereits Benutzer.")
    if not schreibbar():
        raise ValueError(
            f"Das Verzeichnis {config.DATEN_DIR} ist nicht beschreibbar. In der "
            "docker-compose.yml muss ein Volume darauf zeigen, sonst koennen "
            "keine Konten gespeichert werden.")
    return benutzer.anlegen(name, passwort, benutzer.ADMIN)


# --------------------------------------------------------------- Sperren
def gesperrt(*schluessel):
    """Restliche Sperrzeit in Sekunden nach zu vielen Fehlversuchen."""
    rest = 0
    with _schloss:
        for eintrag in (_fehlversuche.get(s) for s in schluessel if s):
            if eintrag:
                rest = max(rest, int(eintrag[1] - time.time()))
    return max(0, rest)


def _fehlversuch(*schluessel):
    with _schloss:
        for s in schluessel:
            if not s:
                continue
            eintrag = _fehlversuche.setdefault(s, [0, 0])
            eintrag[0] += 1
            if eintrag[0] >= MAX_FEHLVERSUCHE:
                eintrag[0] = 0
                eintrag[1] = time.time() + SPERRDAUER


def _zuruecksetzen(*schluessel):
    with _schloss:
        for s in schluessel:
            _fehlversuche.pop(s, None)


# ------------------------------------------------------------- Anmeldung
def anmelden(name, passwort, adresse):
    """Prueft die Zugangsdaten und liefert bei Erfolg ein Sitzungs-Token."""
    name = (name or "").strip()
    rest = gesperrt(adresse, name)
    if rest:
        raise PermissionError(f"Zu viele Fehlversuche. Bitte {rest} Sekunden warten.")

    konto = benutzer.pruefe_anmeldung(name, passwort)
    if konto is None:
        _fehlversuch(adresse, name)
        raise PermissionError("Benutzername oder Passwort ist falsch.")

    _zuruecksetzen(adresse, name)
    token = secrets.token_urlsafe(32)
    with _schloss:
        _aufraeumen()
        _sitzungen[token] = {
            "benutzerId": konto["id"],
            "name": konto["name"],
            "rolle": konto["rolle"],
            "ablauf": time.time() + config.SITZUNGSDAUER,
        }
    return token, konto


def _aufraeumen():
    jetzt = time.time()
    for token in [t for t, s in _sitzungen.items() if s["ablauf"] < jetzt]:
        _sitzungen.pop(token, None)


def sitzung(token):
    """Liefert die Sitzung zu einem Cookie-Token, oder None."""
    if not token:
        return None
    with _schloss:
        _aufraeumen()
        eintrag = _sitzungen.get(token)
        if not eintrag:
            return None
        # Gleitende Verlaengerung: aktive Nutzung haelt die Sitzung offen.
        eintrag["ablauf"] = time.time() + config.SITZUNGSDAUER
        return dict(eintrag)


def gueltig(token):
    return sitzung(token) is not None


def ist_admin(token):
    eintrag = sitzung(token)
    return bool(eintrag and eintrag["rolle"] == benutzer.ADMIN)


def abmelden(token):
    with _schloss:
        _sitzungen.pop(token, None)


def sitzungen_beenden(benutzer_id):
    """Beendet alle Sitzungen eines Kontos - etwa nach einem Passwortwechsel."""
    with _schloss:
        for token in [t for t, s in _sitzungen.items()
                      if s["benutzerId"] == benutzer_id]:
            _sitzungen.pop(token, None)
