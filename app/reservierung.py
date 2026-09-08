"""Reservierung von Slots je Modell und Zeitfenster.

Wer weiss, dass er nachmittags eine groessere Aufgabe rechnen laesst, kann
sich Kapazitaet sichern. Waehrend des Fensters haelt das Portal die
reservierten Slots frei: Andere Nutzer duerfen nur noch die uebrigen belegen,
darueber hinausgehende Anfragen weist der Proxy mit einer Begruendung ab.

Freigehalten wird hart - die Slots bleiben ueber das ganze Fenster reserviert,
auch wenn der Reservierende gerade nichts rechnet. Das ist verlaesslich fuer
ihn und der Grund, warum die Fensterlaenge begrenzt ist.
"""

import threading
import time
from datetime import datetime

from . import benutzer, config

TABELLE = """
CREATE TABLE IF NOT EXISTS reservierungen (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    benutzer_id INTEGER NOT NULL,
    modell      TEXT NOT NULL,
    start       INTEGER NOT NULL,
    ende        INTEGER NOT NULL,
    slots       INTEGER NOT NULL,
    notiz       TEXT,
    erstellt    INTEGER NOT NULL
)
"""

_schloss = threading.Lock()
_vorbereitet = False

# Kurzer Zwischenspeicher fuer den Proxy: Jede Chat-Anfrage fragt die aktiven
# Reservierungen ab - ohne ihn waere das eine Datenbankabfrage je Anfrage.
_CACHE_DAUER = 10.0
_cache = {"zeit": 0.0, "wert": None}


def _db():
    global _vorbereitet
    db = benutzer.verbindung()
    if not _vorbereitet:
        db.execute(TABELLE)
        db.commit()
        _vorbereitet = True
    return db


def _zeitpunkt(wert):
    """Nimmt einen Zeitpunkt entgegen - bevorzugt als Unix-Zeit.

    Die Oberflaeche rechnet den Zeitstempel im Browser aus und schickt eine
    Zahl. Nur so ist der Zeitpunkt eindeutig: Eine Wanduhrzeit ohne Zone wuerde
    der Server in seiner eigenen Zeitzone deuten - laeuft der Container auf UTC
    und sitzt der Nutzer in Berlin, waeren das zwei Stunden Unterschied.

    Text im ISO-Format bleibt als Rueckfall fuer Aufrufe von Hand moeglich; er
    wird in der Zeitzone des Servers gedeutet.
    """
    if isinstance(wert, bool):
        raise ValueError("Unlesbare Zeitangabe.")
    if isinstance(wert, (int, float)):
        return int(wert)
    if isinstance(wert, str) and wert.strip().lstrip("-").isdigit():
        return int(wert.strip())
    try:
        return int(datetime.fromisoformat(wert).timestamp())
    except (TypeError, ValueError):
        raise ValueError(f"Unlesbare Zeitangabe: {wert}")


def _lesbar(zeitstempel):
    return time.strftime("%d.%m. %H:%M", time.localtime(zeitstempel))


def _als_dict(zeile):
    return {
        "id": zeile["id"],
        "benutzerId": zeile["benutzer_id"],
        "benutzer": zeile["name"] if "name" in zeile.keys() else "",
        "modell": zeile["modell"],
        "start": zeile["start"],
        "ende": zeile["ende"],
        "startText": _lesbar(zeile["start"]),
        "endeText": _lesbar(zeile["ende"]),
        "slots": zeile["slots"],
        "notiz": zeile["notiz"] or "",
    }


def _abfrage(bedingung, werte):
    zeilen = _db().execute(
        "SELECT r.*, b.name FROM reservierungen r "
        "LEFT JOIN benutzer b ON b.id = r.benutzer_id "
        f"WHERE {bedingung} ORDER BY r.modell, r.start", werte).fetchall()
    return [_als_dict(z) for z in zeilen]


# ------------------------------------------------------------------- Lesen
def fuer_tag(tag_text=None):
    """Alle Reservierungen eines Kalendertages."""
    if tag_text:
        try:
            tag = datetime.fromisoformat(tag_text + "T00:00")
        except ValueError:
            raise ValueError(f"Unlesbares Datum: {tag_text}")
    else:
        jetzt = datetime.now()
        tag = jetzt.replace(hour=0, minute=0, second=0, microsecond=0)
    beginn = int(tag.timestamp())
    ende = beginn + 86400
    with _schloss:
        # Ueberlappend, nicht nur vollstaendig enthalten - ein Fenster von
        # 23 bis 1 Uhr gehoert zu beiden Tagen.
        return {
            "tag": time.strftime("%Y-%m-%d", time.localtime(beginn)),
            "beginn": beginn,
            "ende": ende,
            "reservierungen": _abfrage("r.ende > ? AND r.start < ?", (beginn, ende)),
        }


def eigene(benutzer_id):
    """Kommende und laufende Reservierungen eines Kontos."""
    with _schloss:
        return _abfrage("r.benutzer_id = ? AND r.ende > ?",
                        (benutzer_id, int(time.time())))


def aktive(zeitpunkt=None):
    """Gerade laufende Reservierungen - mit Zwischenspeicher fuer den Proxy."""
    jetzt = zeitpunkt or int(time.time())
    with _schloss:
        if _cache["wert"] is not None and \
                time.monotonic() - _cache["zeit"] < _CACHE_DAUER and \
                zeitpunkt is None:
            return _cache["wert"]
        ergebnis = _abfrage("r.start <= ? AND r.ende > ?", (jetzt, jetzt))
        if zeitpunkt is None:
            _cache["zeit"] = time.monotonic()
            _cache["wert"] = ergebnis
        return ergebnis


def _cache_leeren():
    _cache["wert"] = None


def je_modell(modell, zeitpunkt=None):
    """Aktive Reservierungen eines Modells, nach Benutzer zusammengefasst."""
    ergebnis = {}
    for eintrag in aktive(zeitpunkt):
        if eintrag["modell"] != modell:
            continue
        name = eintrag["benutzer"] or "?"
        gruppe = ergebnis.setdefault(name, {"slots": 0, "ende": eintrag["ende"]})
        gruppe["slots"] += eintrag["slots"]
        gruppe["ende"] = max(gruppe["ende"], eintrag["ende"])
    return ergebnis


# --------------------------------------------------------------- Schreiben
def anlegen(benutzer_id, ist_admin, modell, start_text, ende_text, slots,
            notiz="", parallel=None):
    """Legt eine Reservierung an, wenn sie die Kapazitaet nicht sprengt."""
    parallel = parallel or config.STANDARD_PARALLEL
    if modell not in [m["id"] for m in config.MODELS]:
        raise ValueError(f"Unbekanntes Modell: {modell}")

    start = _zeitpunkt(start_text)
    ende = _zeitpunkt(ende_text)
    if ende <= start:
        raise ValueError("Das Ende muss nach dem Beginn liegen.")
    if ende <= time.time():
        raise ValueError("Das Zeitfenster liegt in der Vergangenheit.")
    dauer_stunden = (ende - start) / 3600
    if dauer_stunden > config.RESERVIERUNG_MAX_STUNDEN:
        raise ValueError(
            f"Hoechstens {config.RESERVIERUNG_MAX_STUNDEN} Stunden am Stueck.")

    try:
        slots = int(slots)
    except (TypeError, ValueError):
        raise ValueError("Die Slot-Anzahl muss eine Zahl sein.")
    if slots < 1:
        raise ValueError("Mindestens ein Slot.")

    # Normale Nutzer muessen etwas fuer die anderen uebrig lassen, sonst
    # sperrt eine Person den Rest der Abteilung aus.
    grenze = parallel if ist_admin else parallel - config.RESERVIERUNG_MIN_FREI
    if slots > grenze:
        raise ValueError(
            f"Hoechstens {grenze} von {parallel} Slots"
            + ("" if ist_admin else
               f" - {config.RESERVIERUNG_MIN_FREI} bleiben fuer alle anderen frei."))

    with _schloss:
        db = _db()
        belegt = db.execute(
            "SELECT COALESCE(MAX(summe), 0) FROM ("
            "  SELECT SUM(slots) AS summe FROM reservierungen "
            "  WHERE modell = ? AND ende > ? AND start < ?"
            ")", (modell, start, ende)).fetchone()[0]
        if belegt + slots > grenze:
            frei = max(0, grenze - belegt)
            raise ValueError(
                f"In diesem Zeitfenster sind bereits {belegt} Slots reserviert; "
                f"frei sind noch {frei}.")

        zeiger = db.execute(
            "INSERT INTO reservierungen (benutzer_id, modell, start, ende, "
            "slots, notiz, erstellt) VALUES (?,?,?,?,?,?,?)",
            (benutzer_id, modell, start, ende, slots, (notiz or "")[:200],
             int(time.time())))
        db.commit()
        _cache_leeren()
        neue_id = zeiger.lastrowid
        return _abfrage("r.id = ?", (neue_id,))[0]


def loeschen(reservierung_id, benutzer_id, ist_admin):
    with _schloss:
        db = _db()
        zeile = db.execute("SELECT * FROM reservierungen WHERE id = ?",
                           (reservierung_id,)).fetchone()
        if zeile is None:
            raise ValueError("Unbekannte Reservierung.")
        if not ist_admin and zeile["benutzer_id"] != benutzer_id:
            raise ValueError("Nur die eigene Reservierung laesst sich stornieren.")
        db.execute("DELETE FROM reservierungen WHERE id = ?", (reservierung_id,))
        db.commit()
        _cache_leeren()
    return True


def aufraeumen(tage=30):
    """Entfernt lange abgelaufene Reservierungen."""
    with _schloss:
        db = _db()
        db.execute("DELETE FROM reservierungen WHERE ende < ?",
                   (int(time.time()) - tage * 86400,))
        db.commit()
        _cache_leeren()
