"""Messwerte ueber die Zeit aufzeichnen und abfragen.

Ob vier Slots reichen, laesst sich aus einer Momentaufnahme nicht beantworten.
Ein Hintergrund-Thread schreibt daher regelmaessig einen Messpunkt in eine
SQLite-Datei im vorhandenen Datenvolumen; die Verlaufsseite liest daraus.
"""

import os
import sqlite3
import threading
import time

from . import config

_schloss = threading.Lock()
_verbindung = None
_laeuft = False

# Bis hierher wurden Logeintraege bereits gezaehlt (Zeitstempel aus dem Log).
_letzte_anfrage = 0.0

TABELLE = """
CREATE TABLE IF NOT EXISTS messungen (
    zeit          INTEGER PRIMARY KEY,   -- Unixzeit des Messpunkts
    aktiv         INTEGER,               -- belegte Slots
    slots         INTEGER,               -- verfuegbare Slots insgesamt
    modelle       INTEGER,               -- geladene Modelle
    vram_belegt   REAL,                  -- GiB, laut nvidia-smi
    vram_gesamt   REAL,                  -- GiB
    gpu_last      REAL,                  -- Prozent
    anfragen      INTEGER,               -- im Intervall abgeschlossen
    median_s      REAL,                  -- Median der Antwortzeit
    fehler        INTEGER                -- davon fehlerhaft
)
"""


MODELL_TABELLE = """
CREATE TABLE IF NOT EXISTS modell_messungen (
    zeit    INTEGER,
    modell  TEXT,
    aktiv   INTEGER,
    wartend INTEGER,
    PRIMARY KEY (zeit, modell)
)
"""


def _datei():
    return os.path.join(config.DATEN_DIR, "verlauf.sqlite")


def verbindung():
    """Eine gemeinsame Verbindung; SQLite ist hier nur schwach belastet."""
    global _verbindung
    if _verbindung is None:
        os.makedirs(config.DATEN_DIR, exist_ok=True)
        _verbindung = sqlite3.connect(_datei(), check_same_thread=False)
        # WAL: Der Schreib-Thread blockiert die lesenden Anfragen nicht.
        _verbindung.execute("PRAGMA journal_mode=WAL")
        _verbindung.execute(TABELLE)
        _verbindung.execute(MODELL_TABELLE)
        _verbindung.commit()
    return _verbindung


def schreiben(messpunkt):
    with _schloss:
        db = verbindung()
        db.execute(
            "INSERT OR REPLACE INTO messungen (zeit, aktiv, slots, modelle, "
            "vram_belegt, vram_gesamt, gpu_last, anfragen, median_s, fehler) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (int(messpunkt["zeit"]), messpunkt["aktiv"], messpunkt["slots"],
             messpunkt["modelle"], messpunkt["vramBelegt"], messpunkt["vramGesamt"],
             messpunkt["gpuLast"], messpunkt["anfragen"], messpunkt["medianS"],
             messpunkt["fehler"]))
        # Aufschluesselung je Modell gibt es nur im Proxy-Modus.
        for eintrag in messpunkt.get("jeModell") or []:
            db.execute(
                "INSERT OR REPLACE INTO modell_messungen (zeit, modell, aktiv, "
                "wartend) VALUES (?,?,?,?)",
                (int(messpunkt["zeit"]), eintrag["modell"], eintrag["aktiv"],
                 eintrag.get("wartend", 0)))
        db.commit()


def aufraeumen():
    """Loescht Messpunkte, die aelter als VERLAUF_TAGE sind."""
    grenze = int(time.time()) - config.VERLAUF_TAGE * 86400
    with _schloss:
        db = verbindung()
        db.execute("DELETE FROM messungen WHERE zeit < ?", (grenze,))
        db.execute("DELETE FROM modell_messungen WHERE zeit < ?", (grenze,))
        db.commit()


ZEITRAEUME = {
    # Name: (Sekunden, Verdichtung in Sekunden)
    "1h": (3600, 0),
    "24h": (86400, 0),
    "7t": (7 * 86400, 3600),
    "30t": (30 * 86400, 6 * 3600),
}


def lesen(zeitraum="24h"):
    """Messpunkte eines Zeitraums, bei langen Zeitraeumen verdichtet."""
    if zeitraum not in ZEITRAEUME:
        zeitraum = "24h"
    spanne, korn = ZEITRAEUME[zeitraum]
    ab = int(time.time()) - spanne

    with _schloss:
        db = verbindung()
        if korn:
            # Verdichten, damit die Diagramme nicht Tausende Punkte zeichnen:
            # Belegung als Mittel und Spitze, Anfragen als Summe.
            zeilen = db.execute(
                "SELECT (zeit / ?) * ? AS eimer, AVG(aktiv), MAX(aktiv), "
                "MAX(slots), MAX(modelle), AVG(vram_belegt), MAX(vram_gesamt), "
                "AVG(gpu_last), SUM(anfragen), AVG(median_s), SUM(fehler) "
                "FROM messungen WHERE zeit >= ? GROUP BY eimer ORDER BY eimer",
                (korn, korn, ab)).fetchall()
        else:
            zeilen = db.execute(
                "SELECT zeit, aktiv, aktiv, slots, modelle, vram_belegt, "
                "vram_gesamt, gpu_last, anfragen, median_s, fehler "
                "FROM messungen WHERE zeit >= ? ORDER BY zeit", (ab,)).fetchall()

    punkte = [{
        "zeit": int(z[0]),
        "aktiv": round(z[1] or 0, 2),
        "spitze": int(z[2] or 0),
        "slots": int(z[3] or 0),
        "modelle": int(z[4] or 0),
        "vramBelegt": round(z[5] or 0, 2),
        "vramGesamt": round(z[6] or 0, 2),
        "gpuLast": round(z[7] or 0, 1),
        "anfragen": int(z[8] or 0),
        "medianS": round(z[9] or 0, 1),
        "fehler": int(z[10] or 0),
    } for z in zeilen]

    return {
        "ok": True,
        "zeitraum": zeitraum,
        "verdichtung": korn,
        "punkte": punkte,
        "takt": config.VERLAUF_TAKT,
        "aufbewahrungTage": config.VERLAUF_TAGE,
        "zusammenfassung": _zusammenfassung(punkte),
        "jeModell": _je_modell(ab),
    }


def _je_modell(ab):
    """Spitzenbelegung je Modell im Zeitraum - leer ohne Proxy-Modus."""
    with _schloss:
        zeilen = verbindung().execute(
            "SELECT modell, MAX(aktiv), MAX(wartend), COUNT(*) "
            "FROM modell_messungen WHERE zeit >= ? GROUP BY modell "
            "ORDER BY modell", (ab,)).fetchall()
    return [{"modell": z[0], "spitze": int(z[1] or 0),
             "wartendSpitze": int(z[2] or 0), "messpunkte": int(z[3] or 0)}
            for z in zeilen]


def _zusammenfassung(punkte):
    if not punkte:
        return {}
    anfragen = sum(p["anfragen"] for p in punkte)
    mit_last = [p for p in punkte if p["anfragen"]]
    return {
        "anfragen": anfragen,
        "fehler": sum(p["fehler"] for p in punkte),
        "spitzeSlots": max(p["spitze"] for p in punkte),
        "slots": max(p["slots"] for p in punkte),
        "vramSpitze": max(p["vramBelegt"] for p in punkte),
        "vramGesamt": max(p["vramGesamt"] for p in punkte),
        # Mittel nur ueber Zeitraeume mit Last - sonst druecken die Nachtstunden
        # jede Antwortzeit auf null.
        "medianS": (round(sum(p["medianS"] for p in mit_last) / len(mit_last), 1)
                    if mit_last else 0.0),
        "punkte": len(punkte),
    }


def _messpunkt(sammler):
    """Erhebt einen Messpunkt. sammler liefert die Rohdaten."""
    global _letzte_anfrage
    daten = sammler(_letzte_anfrage)
    _letzte_anfrage = daten.get("letzteAnfrage", _letzte_anfrage)
    return {
        "zeit": time.time(),
        "aktiv": daten.get("aktiv", 0),
        "slots": daten.get("slots", 0),
        "modelle": daten.get("modelle", 0),
        "vramBelegt": daten.get("vramBelegt", 0.0),
        "vramGesamt": daten.get("vramGesamt", 0.0),
        "gpuLast": daten.get("gpuLast", 0.0),
        "anfragen": daten.get("anfragen", 0),
        "medianS": daten.get("medianS", 0.0),
        "fehler": daten.get("fehler", 0),
        "jeModell": daten.get("jeModell") or [],
    }


def _schleife(sammler):
    naechstes_aufraeumen = 0
    while True:
        try:
            schreiben(_messpunkt(sammler))
            if time.time() > naechstes_aufraeumen:
                aufraeumen()
                naechstes_aufraeumen = time.time() + 3600
        except Exception as fehler:  # der Thread darf nie sterben
            print(f"Verlauf: Messpunkt uebersprungen ({type(fehler).__name__}: "
                  f"{fehler})", flush=True)
        time.sleep(config.VERLAUF_TAKT)


def starten(sammler):
    """Startet die Aufzeichnung einmalig."""
    global _laeuft
    if _laeuft or not config.VERLAUF_AKTIV:
        return False
    _laeuft = True
    threading.Thread(target=_schleife, args=(sammler,), daemon=True).start()
    return True
