"""Echte GPU-Werte ueber nvidia-smi im Ollama-Container.

Der VRAM-Rechner verglich seine Schaetzung bisher gegen den fest
eingestellten Wert GPU_VRAM_GIB. Hier kommen die tatsaechlichen Werte her:
Das NVIDIA-Container-Runtime legt nvidia-smi in den Ollama-Container, und
ueber den Docker-Socket laesst es sich dort aufrufen.
"""

import threading
import time

from . import config, dockerctl

FELDER = ("name", "memory.total", "memory.used", "utilization.gpu",
          "temperature.gpu", "power.draw")

# Kurzer Zwischenspeicher: Die Uebersicht fragt GPU, VRAM und Hinweise
# gleichzeitig ab - ohne ihn waeren das drei exec-Aufrufe je Aktualisierung.
_CACHE_DAUER = 5.0
_schloss = threading.Lock()
_cache = {"zeit": 0.0, "wert": None}


def _zahl(text):
    """Wandelt ein Feld in eine Zahl; nvidia-smi meldet sonst [N/A]."""
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _abfragen():
    befehl = ["nvidia-smi", "--query-gpu=" + ",".join(FELDER),
              "--format=csv,noheader,nounits"]
    try:
        ausgabe = dockerctl.ausfuehren(befehl)
    except dockerctl.DockerFehler as fehler:
        return {
            "ok": False,
            "fehler": str(fehler),
            "gpus": [],
            "vramGib": config.GPU_VRAM_GIB,
            "gemessen": False,
            "hilfe": ("nvidia-smi liegt nur im Container, wenn er mit dem "
                      "NVIDIA-Runtime gestartet wurde. Ohne die Messung "
                      "rechnet das Portal weiter mit GPU_VRAM_GIB."),
        }

    gpus = []
    for zeile in ausgabe.splitlines():
        felder = [teil.strip() for teil in zeile.split(",")]
        if len(felder) < len(FELDER) or not felder[0]:
            continue
        gesamt = _zahl(felder[1])
        belegt = _zahl(felder[2])
        if gesamt is None:
            continue
        gpus.append({
            "name": felder[0],
            # nvidia-smi rechnet in MiB.
            "vramGesamtGib": round(gesamt / 1024, 2),
            "vramBelegtGib": round((belegt or 0) / 1024, 2),
            "vramFreiGib": round((gesamt - (belegt or 0)) / 1024, 2),
            "auslastung": _zahl(felder[3]),
            "temperatur": _zahl(felder[4]),
            "leistungWatt": _zahl(felder[5]),
        })

    if not gpus:
        return {
            "ok": False,
            "fehler": "nvidia-smi lieferte keine verwertbare Ausgabe: "
                      + ausgabe.strip()[:200],
            "gpus": [],
            "vramGib": config.GPU_VRAM_GIB,
            "gemessen": False,
        }

    return {
        "ok": True,
        "gpus": gpus,
        # Mehrere Karten werden zusammengefasst: Ollama verteilt ein Modell
        # bei Bedarf ueber alle sichtbaren GPUs.
        "vramGib": round(sum(g["vramGesamtGib"] for g in gpus), 2),
        "vramBelegtGib": round(sum(g["vramBelegtGib"] for g in gpus), 2),
        "gemessen": True,
        "anzahl": len(gpus),
    }


def werte(frisch=False):
    """GPU-Werte, hoechstens alle paar Sekunden neu erhoben."""
    with _schloss:
        jetzt = time.monotonic()
        if not frisch and _cache["wert"] is not None and \
                jetzt - _cache["zeit"] < _CACHE_DAUER:
            return _cache["wert"]
        ergebnis = _abfragen()
        _cache["zeit"] = jetzt
        _cache["wert"] = ergebnis
        return ergebnis


def vram_gib():
    """Verfuegbarer VRAM fuer den Rechner - gemessen, sonst konfiguriert."""
    daten = werte()
    return daten["vramGib"] if daten.get("gemessen") else config.GPU_VRAM_GIB
