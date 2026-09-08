"""Benutzerkonten mit Rollen.

Bis hierher kannte das Portal genau ein gemeinsames Passwort. Wer es hatte,
durfte alles. Jetzt gibt es Konten mit zwei Rollen:

    admin  - darf Einstellungen aendern, Modelle verwalten, Konten anlegen
    nutzer - darf sich anmelden, den eigenen Zugangsschluessel sehen und
             Reservierungen verwalten

Gespeichert wird wie bisher nur ein PBKDF2-HMAC-SHA256-Hash mit zufaelligem
Salz. Vom Zugangsschluessel (Token) liegt nur ein SHA-256-Abdruck in der
Datenbank: Er hat genug Entropie, dass ein schneller Digest genuegt - im
Klartext ist er nur unmittelbar nach dem Erzeugen sichtbar.
"""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time

from . import config

ALGORITHMUS = "pbkdf2_sha256"
ITERATIONEN = 240_000
MIN_LAENGE = 8
TOKEN_PRAEFIX = "mp_"

ADMIN = "admin"
NUTZER = "nutzer"
ROLLEN = (ADMIN, NUTZER)

TABELLE = """
CREATE TABLE IF NOT EXISTS benutzer (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT UNIQUE NOT NULL,
    rolle         TEXT NOT NULL,
    salz          TEXT NOT NULL,
    hash          TEXT NOT NULL,
    iterationen   INTEGER NOT NULL,
    token_hash    TEXT UNIQUE,
    aktiv         INTEGER NOT NULL DEFAULT 1,
    erstellt      INTEGER NOT NULL,
    letzter_login INTEGER
)
"""

_schloss = threading.Lock()
_verbindung = None


# ------------------------------------------------------------------ Ablage
def _datei():
    return os.path.join(config.DATEN_DIR, "portal.sqlite")


def verbindung():
    global _verbindung
    if _verbindung is None:
        os.makedirs(config.DATEN_DIR, exist_ok=True)
        _verbindung = sqlite3.connect(_datei(), check_same_thread=False)
        _verbindung.row_factory = sqlite3.Row
        _verbindung.execute("PRAGMA journal_mode=WAL")
        _verbindung.execute(TABELLE)
        _verbindung.commit()
    return _verbindung


# ------------------------------------------------------------ Passwoerter
def hashe(passwort, salz=None, iterationen=ITERATIONEN):
    """PBKDF2-Hash eines Passworts. Auch von der Migration genutzt."""
    salz = salz or secrets.token_bytes(16)
    roh = hashlib.pbkdf2_hmac("sha256", passwort.encode("utf-8"), salz, iterationen)
    return {"salz": salz.hex(), "hash": roh.hex(), "iterationen": iterationen}


def _passwort_stimmt(zeile, passwort):
    if not passwort:
        return False
    try:
        vergleich = hashlib.pbkdf2_hmac(
            "sha256", passwort.encode("utf-8"),
            bytes.fromhex(zeile["salz"]), int(zeile["iterationen"]))
    except (KeyError, ValueError, TypeError):
        return False
    return hmac.compare_digest(vergleich.hex(), zeile["hash"])


def _token_abdruck(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _neuer_token():
    return TOKEN_PRAEFIX + secrets.token_urlsafe(24)


def _pruefe_name(name):
    name = (name or "").strip()
    if not 2 <= len(name) <= 64:
        raise ValueError("Der Benutzername muss zwischen 2 und 64 Zeichen haben.")
    if any(zeichen.isspace() for zeichen in name):
        raise ValueError("Der Benutzername darf keine Leerzeichen enthalten.")
    return name


def _pruefe_passwort(passwort):
    if len(passwort or "") < MIN_LAENGE:
        raise ValueError(f"Das Passwort muss mindestens {MIN_LAENGE} Zeichen haben.")


def _als_dict(zeile, mit_token=False):
    if zeile is None:
        return None
    eintrag = {
        "id": zeile["id"],
        "name": zeile["name"],
        "rolle": zeile["rolle"],
        "aktiv": bool(zeile["aktiv"]),
        "erstellt": time.strftime("%Y-%m-%d", time.localtime(zeile["erstellt"])),
        "letzterLogin": (time.strftime("%Y-%m-%d %H:%M",
                                       time.localtime(zeile["letzter_login"]))
                         if zeile["letzter_login"] else ""),
        "hatToken": bool(zeile["token_hash"]),
    }
    if mit_token:
        eintrag["tokenAbdruck"] = (zeile["token_hash"] or "")[:8]
    return eintrag


# ------------------------------------------------------------------ Lesen
def anzahl():
    with _schloss:
        return verbindung().execute("SELECT COUNT(*) FROM benutzer").fetchone()[0]


def eingerichtet():
    return anzahl() > 0


def liste():
    with _schloss:
        zeilen = verbindung().execute(
            "SELECT * FROM benutzer ORDER BY rolle, name").fetchall()
    return [_als_dict(z, mit_token=True) for z in zeilen]


def finde(benutzer_id):
    with _schloss:
        zeile = verbindung().execute(
            "SELECT * FROM benutzer WHERE id = ?", (benutzer_id,)).fetchone()
    return _als_dict(zeile)


def finde_nach_token(token):
    """Bestimmt den Benutzer zu einem Zugangsschluessel."""
    if not token:
        return None
    with _schloss:
        zeile = verbindung().execute(
            "SELECT * FROM benutzer WHERE token_hash = ? AND aktiv = 1",
            (_token_abdruck(token),)).fetchone()
    return _als_dict(zeile)


def pruefe_anmeldung(name, passwort):
    """Prueft Name und Passwort. Liefert den Benutzer oder None."""
    with _schloss:
        zeile = verbindung().execute(
            "SELECT * FROM benutzer WHERE name = ? AND aktiv = 1",
            ((name or "").strip(),)).fetchone()
    if zeile is None or not _passwort_stimmt(zeile, passwort):
        return None
    with _schloss:
        db = verbindung()
        db.execute("UPDATE benutzer SET letzter_login = ? WHERE id = ?",
                   (int(time.time()), zeile["id"]))
        db.commit()
    return _als_dict(zeile)


# --------------------------------------------------------------- Schreiben
def anlegen(name, passwort, rolle=NUTZER):
    """Legt ein Konto an und liefert es samt frisch erzeugtem Token."""
    name = _pruefe_name(name)
    _pruefe_passwort(passwort)
    if rolle not in ROLLEN:
        raise ValueError(f"Unbekannte Rolle: {rolle}")

    daten = hashe(passwort)
    token = _neuer_token()
    with _schloss:
        db = verbindung()
        if db.execute("SELECT 1 FROM benutzer WHERE name = ?", (name,)).fetchone():
            raise ValueError(f"Den Benutzer '{name}' gibt es bereits.")
        zeiger = db.execute(
            "INSERT INTO benutzer (name, rolle, salz, hash, iterationen, "
            "token_hash, aktiv, erstellt) VALUES (?,?,?,?,?,?,1,?)",
            (name, rolle, daten["salz"], daten["hash"], daten["iterationen"],
             _token_abdruck(token), int(time.time())))
        db.commit()
        neu_id = zeiger.lastrowid
    return {"benutzer": finde(neu_id), "token": token}


def aendern(benutzer_id, rolle=None, aktiv=None):
    with _schloss:
        db = verbindung()
        zeile = db.execute("SELECT * FROM benutzer WHERE id = ?",
                           (benutzer_id,)).fetchone()
        if zeile is None:
            raise ValueError("Unbekannter Benutzer.")
        if rolle is not None:
            if rolle not in ROLLEN:
                raise ValueError(f"Unbekannte Rolle: {rolle}")
            # Der letzte aktive Admin darf sich nicht selbst entmachten -
            # sonst kommt niemand mehr an die Einstellungen.
            if zeile["rolle"] == ADMIN and rolle != ADMIN and \
                    _andere_admins(db, benutzer_id) == 0:
                raise ValueError("Das ist der letzte Admin - Rolle bleibt bestehen.")
            db.execute("UPDATE benutzer SET rolle = ? WHERE id = ?",
                       (rolle, benutzer_id))
        if aktiv is not None:
            if not aktiv and zeile["rolle"] == ADMIN and \
                    _andere_admins(db, benutzer_id) == 0:
                raise ValueError("Das ist der letzte Admin - er bleibt aktiv.")
            db.execute("UPDATE benutzer SET aktiv = ? WHERE id = ?",
                       (1 if aktiv else 0, benutzer_id))
        db.commit()
    return finde(benutzer_id)


def _andere_admins(db, ausser_id):
    return db.execute(
        "SELECT COUNT(*) FROM benutzer WHERE rolle = ? AND aktiv = 1 AND id != ?",
        (ADMIN, ausser_id)).fetchone()[0]


def passwort_setzen(benutzer_id, passwort):
    _pruefe_passwort(passwort)
    daten = hashe(passwort)
    with _schloss:
        db = verbindung()
        if db.execute("SELECT 1 FROM benutzer WHERE id = ?",
                      (benutzer_id,)).fetchone() is None:
            raise ValueError("Unbekannter Benutzer.")
        db.execute("UPDATE benutzer SET salz = ?, hash = ?, iterationen = ? "
                   "WHERE id = ?",
                   (daten["salz"], daten["hash"], daten["iterationen"], benutzer_id))
        db.commit()
    return True


def passwort_aendern(benutzer_id, alt, neu):
    """Aendert das eigene Passwort - das bisherige muss stimmen."""
    with _schloss:
        zeile = verbindung().execute("SELECT * FROM benutzer WHERE id = ?",
                                     (benutzer_id,)).fetchone()
    if zeile is None or not _passwort_stimmt(zeile, alt):
        raise ValueError("Das bisherige Passwort ist falsch.")
    return passwort_setzen(benutzer_id, neu)


def token_erneuern(benutzer_id):
    """Erzeugt einen neuen Zugangsschluessel. Der alte wird sofort ungueltig."""
    token = _neuer_token()
    with _schloss:
        db = verbindung()
        if db.execute("SELECT 1 FROM benutzer WHERE id = ?",
                      (benutzer_id,)).fetchone() is None:
            raise ValueError("Unbekannter Benutzer.")
        db.execute("UPDATE benutzer SET token_hash = ? WHERE id = ?",
                   (_token_abdruck(token), benutzer_id))
        db.commit()
    return token


def loeschen(benutzer_id):
    with _schloss:
        db = verbindung()
        zeile = db.execute("SELECT * FROM benutzer WHERE id = ?",
                           (benutzer_id,)).fetchone()
        if zeile is None:
            raise ValueError("Unbekannter Benutzer.")
        if zeile["rolle"] == ADMIN and _andere_admins(db, benutzer_id) == 0:
            raise ValueError("Das ist der letzte Admin - er kann nicht "
                             "geloescht werden.")
        db.execute("DELETE FROM benutzer WHERE id = ?", (benutzer_id,))
        db.commit()
    return True


# ------------------------------------------------------------- Uebernahme
def uebernehme_altes_passwort():
    """Macht aus dem bisherigen Einzelpasswort den ersten Admin.

    Die alte /data/auth.json enthaelt denselben PBKDF2-Hash, den auch die
    Benutzertabelle nutzt - er wird uebernommen, das bisherige Passwort gilt
    also unveraendert weiter, nur eben fuer den Benutzer 'admin'.
    """
    if eingerichtet():
        return None
    pfad = os.path.join(config.DATEN_DIR, "auth.json")
    try:
        with open(pfad, "r", encoding="utf-8") as datei:
            alt = json.load(datei)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not {"salz", "hash", "iterationen"} <= set(alt):
        return None

    with _schloss:
        db = verbindung()
        db.execute(
            "INSERT INTO benutzer (name, rolle, salz, hash, iterationen, "
            "token_hash, aktiv, erstellt) VALUES (?,?,?,?,?,?,1,?)",
            ("admin", ADMIN, alt["salz"], alt["hash"], int(alt["iterationen"]),
             _token_abdruck(_neuer_token()), int(time.time())))
        db.commit()
    # Die alte Datei bleibt liegen: Sie schadet nicht und ist der Nachweis,
    # woher das Passwort stammt. Ein zweites Mal greift die Migration nicht,
    # weil dann bereits ein Benutzer existiert.
    return "admin"
