"""Modellverwaltung: auflisten, nachladen, loeschen.

Damit entfaellt der Weg ueber SSH auf den GPU-Server, wenn ein Modell
aktualisiert oder ein neues ausprobiert werden soll.
"""

import threading
import time
import urllib.error

from . import config, dockerctl, ollama

# Laufender oder letzter Ladevorgang. Nur einer gleichzeitig - zwei
# parallele Pulls wuerden sich die Bandbreite und die Platte streitig machen.
_schloss = threading.Lock()
_fortschritt = {
    "aktiv": False,
    "modell": "",
    "status": "",
    "prozent": 0.0,
    "geladenGib": 0.0,
    "gesamtGib": 0.0,
    "fehler": "",
    "fertig": False,
    "begonnen": "",
    "beendet": "",
}


def _gib(bytes_wert):
    return round((bytes_wert or 0) / 1024 ** 3, 2)


def liste():
    """Installierte Modelle mit Groesse, Stand und Quantisierung."""
    antwort = ollama._request("GET", "/api/tags", timeout=30)
    if not antwort["ok"]:
        return {"ok": False, "fehler": antwort.get("fehler", "unbekannter Fehler"),
                "modelle": []}

    modelle = []
    for eintrag in (antwort.get("body") or {}).get("models", []):
        einzelheiten = eintrag.get("details") or {}
        name = eintrag.get("model") or eintrag.get("name", "")
        modelle.append({
            "name": name,
            "groesseGib": _gib(eintrag.get("size")),
            "geaendert": (eintrag.get("modified_at") or "")[:19].replace("T", " "),
            "quantisierung": einzelheiten.get("quantization_level", ""),
            "parameter": einzelheiten.get("parameter_size", ""),
            "familie": einzelheiten.get("family", ""),
            # Modelle aus der Portal-Konfiguration stehen in der
            # chatLanguageModels.json der Nutzer und sind besonders geschuetzt.
            "inKonfiguration": any(m["id"] == name for m in config.MODELS),
        })
    modelle.sort(key=lambda m: m["name"])
    return {
        "ok": True,
        "modelle": modelle,
        "summeGib": round(sum(m["groesseGib"] for m in modelle), 2),
        "platte": _plattenplatz(),
    }


def _plattenplatz():
    """Belegung des Modellverzeichnisses im Ollama-Container."""
    try:
        ausgabe = dockerctl.ausfuehren(
            ["df", "-h", "/root/.ollama"], timeout=15)
    except dockerctl.DockerFehler as fehler:
        return {"ok": False, "fehler": str(fehler)}
    zeilen = [z for z in ausgabe.splitlines() if z.strip()]
    for zeile in reversed(zeilen):
        felder = zeile.split()
        # Die Datenzeile von df erkennt man an der Prozentspalte. Ohne diese
        # Pruefung wuerde jede beliebige Ausgabe als Belegung durchgehen.
        if len(felder) >= 5 and felder[4].endswith("%"):
            return {"ok": True, "gesamt": felder[1], "belegt": felder[2],
                    "frei": felder[3], "anteil": felder[4]}
    return {"ok": False,
            "fehler": "df lieferte keine verwertbare Ausgabe: "
                      + ausgabe.strip()[:120]}


def details(name):
    antwort = ollama._request("POST", "/api/show", {"model": name}, timeout=30)
    if not antwort["ok"]:
        return {"ok": False, "fehler": antwort.get("fehler", "unbekannter Fehler")}
    rumpf = antwort.get("body") or {}
    info = rumpf.get("model_info") or {}
    return {
        "ok": True,
        "name": name,
        "einzelheiten": rumpf.get("details") or {},
        "kontextlaenge": next((wert for schluessel, wert in info.items()
                               if schluessel.endswith(".context_length")), None),
        "faehigkeiten": rumpf.get("capabilities") or [],
    }


def fortschritt():
    with _schloss:
        return dict(_fortschritt)


def _setze(**werte):
    with _schloss:
        _fortschritt.update(werte)


def _laden(name):
    """Laeuft im Hintergrund und schreibt den Fortschritt mit."""
    try:
        for meldung in ollama.strom("POST", "/api/pull", {"model": name, "stream": True},
                                    timeout=None):
            if meldung.get("error"):
                _setze(fehler=str(meldung["error"]), aktiv=False, fertig=True,
                       beendet=time.strftime("%H:%M:%S"))
                return
            neu = {"status": meldung.get("status", "")}
            # Nur Meldungen mit Fortschrittsfeldern aktualisieren die Zahlen -
            # die Abschlussmeldung ("success") traegt keine und wuerde sie
            # sonst auf null zuruecksetzen.
            if meldung.get("total"):
                gesamt = meldung["total"]
                geladen = meldung.get("completed") or 0
                neu.update({
                    "gesamtGib": _gib(gesamt),
                    "geladenGib": _gib(geladen),
                    "prozent": round(geladen / gesamt * 100, 1),
                })
            _setze(**neu)
        _setze(aktiv=False, fertig=True, status="fertig", prozent=100.0,
               beendet=time.strftime("%H:%M:%S"))
    except (urllib.error.URLError, OSError) as fehler:
        _setze(fehler=f"Verbindung zu Ollama abgebrochen: {fehler}",
               aktiv=False, fertig=True, beendet=time.strftime("%H:%M:%S"))
    except Exception as fehler:  # nichts darf den Thread still sterben lassen
        _setze(fehler=f"{type(fehler).__name__}: {fehler}", aktiv=False,
               fertig=True, beendet=time.strftime("%H:%M:%S"))


def laden(name):
    """Startet den Ladevorgang, wenn keiner laeuft."""
    if not name or "/" in name and name.count("/") > 1:
        raise ValueError("Ungueltiger Modellname.")
    with _schloss:
        if _fortschritt["aktiv"]:
            raise ValueError(
                f"Es laeuft bereits ein Ladevorgang ({_fortschritt['modell']}).")
        _fortschritt.update({
            "aktiv": True, "modell": name, "status": "wird gestartet",
            "prozent": 0.0, "geladenGib": 0.0, "gesamtGib": 0.0,
            "fehler": "", "fertig": False,
            "begonnen": time.strftime("%H:%M:%S"), "beendet": "",
        })
    threading.Thread(target=_laden, args=(name,), daemon=True).start()
    return {"ok": True, "modell": name}


def loeschen(name, bestaetigt=False):
    """Loescht ein Modell. In der Konfiguration genannte nur mit Bestaetigung."""
    if not name:
        raise ValueError("Kein Modell angegeben.")
    if any(m["id"] == name for m in config.MODELS) and not bestaetigt:
        raise ValueError(
            f"{name} steht in der chatLanguageModels.json der Nutzer. "
            "Nach dem Loeschen findet VS Code das Modell nicht mehr. "
            "Zum Fortfahren ausdruecklich bestaetigen.")
    # Aeltere Ollama-Staende erwarten "name", neuere "model".
    antwort = ollama._request("DELETE", "/api/delete",
                              {"model": name, "name": name}, timeout=60)
    if not antwort["ok"]:
        raise ValueError(antwort.get("fehler", "unbekannter Fehler"))
    return {"ok": True, "geloescht": name}
