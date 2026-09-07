"""Passwortschutz fuer die Einstellungsseite.

Beim ersten Aufruf legt der Nutzer ein Passwort fest. Gespeichert wird nur
ein PBKDF2-HMAC-SHA256-Hash mit zufaelligem Salz - das Passwort selbst
verlaesst den Browser nie im Klartext und liegt nirgends auf der Platte.

Nach der Anmeldung erhaelt der Browser ein zufaelliges Sitzungs-Token als
HttpOnly-Cookie. Die Sitzungen liegen nur im Arbeitsspeicher und sind nach
einem Neustart des Portals ungueltig.
"""

import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from . import config

ALGORITHMUS = "pbkdf2_sha256"
ITERATIONEN = 240_000
MIN_LAENGE = 8

# Anmeldeversuche je Adresse, um Durchprobieren auszubremsen.
MAX_FEHLVERSUCHE = 5
SPERRDAUER = 60

_schloss = threading.Lock()
_sitzungen = {}       # Token -> Ablaufzeitpunkt
_fehlversuche = {}    # Adresse -> [Anzahl, gesperrt_bis]


# ------------------------------------------------------------------ Ablage
def _dateipfad():
    return os.path.join(config.DATEN_DIR, "auth.json")


def _lade():
    try:
        with open(_dateipfad(), "r", encoding="utf-8") as datei:
            return json.load(datei)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _speichere(eintrag):
    os.makedirs(config.DATEN_DIR, exist_ok=True)
    pfad = _dateipfad()
    # Erst in eine Nebendatei schreiben, dann umbenennen: so bleibt bei einem
    # Abbruch nie eine halb geschriebene Datei zurueck.
    vorlaeufig = pfad + ".neu"
    with open(vorlaeufig, "w", encoding="utf-8") as datei:
        json.dump(eintrag, datei, indent=2)
    os.replace(vorlaeufig, pfad)
    try:
        os.chmod(pfad, 0o600)
    except OSError:
        pass


def _hashe(passwort, salz=None, iterationen=ITERATIONEN):
    salz = salz or secrets.token_bytes(16)
    roh = hashlib.pbkdf2_hmac("sha256", passwort.encode("utf-8"), salz, iterationen)
    return {
        "algorithmus": ALGORITHMUS,
        "iterationen": iterationen,
        "salz": salz.hex(),
        "hash": roh.hex(),
        "geaendert": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ---------------------------------------------------------------- Zustand
def per_umgebung():
    """True, wenn das Passwort fest per PORTAL_PASSWORT vorgegeben ist."""
    return bool(config.PORTAL_PASSWORT)


def eingerichtet():
    return per_umgebung() or _lade() is not None


def schreibbar():
    """Prueft, ob das Datenverzeichnis beschreibbar ist."""
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
        "minLaenge": MIN_LAENGE,
    }


# ------------------------------------------------------------- Einrichtung
def einrichten(passwort):
    """Legt das Passwort beim ersten Aufruf fest."""
    if eingerichtet():
        raise ValueError("Es ist bereits ein Passwort gesetzt.")
    if len(passwort or "") < MIN_LAENGE:
        raise ValueError(f"Das Passwort muss mindestens {MIN_LAENGE} Zeichen haben.")
    if not schreibbar():
        raise ValueError(
            f"Das Verzeichnis {config.DATEN_DIR} ist nicht beschreibbar. In der "
            "docker-compose.yml muss ein Volume darauf zeigen, sonst kann das "
            "Passwort nicht dauerhaft gespeichert werden.")
    _speichere(_hashe(passwort))
    return True


def passwort_aendern(alt, neu):
    if per_umgebung():
        raise ValueError("Das Passwort ist per PORTAL_PASSWORT fest vorgegeben "
                         "und kann hier nicht geaendert werden.")
    if not _stimmt(alt):
        raise ValueError("Das bisherige Passwort ist falsch.")
    if len(neu or "") < MIN_LAENGE:
        raise ValueError(f"Das neue Passwort muss mindestens {MIN_LAENGE} Zeichen haben.")
    _speichere(_hashe(neu))
    # Alle offenen Sitzungen beenden - inklusive der eigenen.
    with _schloss:
        _sitzungen.clear()
    return True


def _stimmt(passwort):
    if not passwort:
        return False
    if per_umgebung():
        return hmac.compare_digest(passwort, config.PORTAL_PASSWORT)
    eintrag = _lade()
    if not eintrag:
        return False
    try:
        vergleich = hashlib.pbkdf2_hmac(
            "sha256", passwort.encode("utf-8"),
            bytes.fromhex(eintrag["salz"]), int(eintrag["iterationen"]))
    except (KeyError, ValueError):
        return False
    return hmac.compare_digest(vergleich.hex(), eintrag["hash"])


# --------------------------------------------------------------- Sitzungen
def _aufraeumen():
    jetzt = time.time()
    for token in [t for t, ablauf in _sitzungen.items() if ablauf < jetzt]:
        _sitzungen.pop(token, None)


def gesperrt(adresse):
    """Restliche Sperrzeit in Sekunden nach zu vielen Fehlversuchen."""
    with _schloss:
        eintrag = _fehlversuche.get(adresse)
        if not eintrag:
            return 0
        rest = int(eintrag[1] - time.time())
        return max(0, rest)


def anmelden(passwort, adresse):
    """Prueft das Passwort und liefert bei Erfolg ein Sitzungs-Token."""
    rest = gesperrt(adresse)
    if rest:
        raise PermissionError(
            f"Zu viele Fehlversuche. Bitte {rest} Sekunden warten.")

    if not _stimmt(passwort):
        with _schloss:
            eintrag = _fehlversuche.setdefault(adresse, [0, 0])
            eintrag[0] += 1
            if eintrag[0] >= MAX_FEHLVERSUCHE:
                eintrag[0] = 0
                eintrag[1] = time.time() + SPERRDAUER
        raise PermissionError("Falsches Passwort.")

    with _schloss:
        _fehlversuche.pop(adresse, None)
        _aufraeumen()
        token = secrets.token_urlsafe(32)
        _sitzungen[token] = time.time() + config.SITZUNGSDAUER
    return token


def gueltig(token):
    if not token:
        return False
    with _schloss:
        _aufraeumen()
        ablauf = _sitzungen.get(token)
        if not ablauf:
            return False
        # Gleitende Verlaengerung: aktive Nutzung haelt die Sitzung offen.
        _sitzungen[token] = time.time() + config.SITZUNGSDAUER
    return True


def abmelden(token):
    with _schloss:
        _sitzungen.pop(token, None)
