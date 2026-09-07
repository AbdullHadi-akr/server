"""Slot-Auslastung aus den Zugriffslogs des Ollama-Containers.

Ollama protokolliert jede beantwortete Anfrage im GIN-Format, zum Beispiel:

    [GIN] 2026/09/07 - 10:14:02 | 200 |  3.523456s | 10.0.0.5 | POST "/api/chat"

Aus Endzeitpunkt und Dauer laesst sich das Zeitfenster jeder Anfrage
rekonstruieren und daraus, wie viele Slots gleichzeitig belegt waren.

Grenze des Verfahrens: Eine Zeile entsteht erst, wenn die Anfrage fertig
ist. Gerade laufende Anfragen sind darin also noch nicht enthalten - die
Auswertung zeigt die Belegung des zurueckliegenden Zeitfensters, keine
Momentaufnahme. Das Modell steht nicht in der Zeile; die Zahlen gelten
daher fuer den Ollama-Dienst insgesamt.
"""

import re
from datetime import datetime

# [GIN] Datum - Uhrzeit | Status | Dauer | Adresse | Methode "Pfad"
ZEILE = re.compile(
    r"\[GIN\]\s*(?P<zeit>\d{4}/\d{2}/\d{2} - \d{2}:\d{2}:\d{2})\s*\|"
    r"\s*(?P<status>\d{3})\s*\|"
    # Die Dauer bis zum naechsten Trenner nehmen: GIN schreibt
    # zusammengesetzte Angaben wie "1m3.4s" ohne Trennzeichen.
    r"\s*(?P<dauer>[^|]+?)\s*\|"
    r"[^|]*\|"
    r"\s*(?P<methode>[A-Z]+)\s+\"(?P<pfad>[^\"]+)\"")

# Zusammengesetzte Dauern wie "1m3.2s" schreibt GIN ohne Trennzeichen.
ZUSAMMEN = re.compile(r"(?P<zahl>[0-9.]+)(?P<einheit>ns|µs|us|ms|s|m|h)")

FAKTOR = {"ns": 1e-9, "µs": 1e-6, "us": 1e-6, "ms": 1e-3, "s": 1.0,
          "m": 60.0, "h": 3600.0}

# Nur Anfragen, die tatsaechlich einen Slot belegen.
SLOT_PFADE = ("/api/chat", "/api/generate", "/v1/chat/completions",
              "/v1/completions", "/api/embed", "/api/embeddings")


def _dauer_sekunden(text):
    """Wandelt eine GIN-Dauer wie '1m3.2s' oder '523.5ms' in Sekunden."""
    gesamt = 0.0
    for treffer in ZUSAMMEN.finditer(text):
        gesamt += float(treffer.group("zahl")) * FAKTOR[treffer.group("einheit")]
    return gesamt


def _anfragen(logtext):
    """Liest alle Slot-belegenden Anfragen aus dem Logtext."""
    ergebnis = []
    for zeile in logtext.splitlines():
        treffer = ZEILE.search(zeile)
        if not treffer:
            continue
        pfad = treffer.group("pfad")
        if not any(pfad.startswith(p) for p in SLOT_PFADE):
            continue
        try:
            ende = datetime.strptime(treffer.group("zeit"), "%Y/%m/%d - %H:%M:%S")
        except ValueError:
            continue
        ergebnis.append({
            "ende": ende.timestamp(),
            "dauer": _dauer_sekunden(treffer.group("dauer")),
            "status": int(treffer.group("status")),
            "pfad": pfad,
        })
    return ergebnis


def _gleichzeitig(anfragen):
    """Hoechste Zahl gleichzeitig laufender Anfragen (Sweep-Line)."""
    ereignisse = []
    for eintrag in anfragen:
        ereignisse.append((eintrag["ende"] - eintrag["dauer"], 1))
        ereignisse.append((eintrag["ende"], -1))
    ereignisse.sort()
    aktuell = spitze = 0
    for _, richtung in ereignisse:
        aktuell += richtung
        spitze = max(spitze, aktuell)
    return spitze


def auswerten(logtext, slots, fenster_minuten=(15, 60)):
    """Fasst die Auslastung fuer mehrere Zeitfenster zusammen."""
    anfragen = _anfragen(logtext)
    if not anfragen:
        return {
            "ok": True,
            "erkannt": 0,
            "slots": slots,
            "fenster": [],
            "hinweis": ("Im vorliegenden Logausschnitt stehen keine "
                        "abgeschlossenen Modellanfragen."),
        }

    # Als Bezugspunkt dient der juengste Logeintrag, nicht die Uhr des
    # Portals - so spielt eine abweichende Zeitzone des Containers keine Rolle.
    jetzt = max(a["ende"] for a in anfragen)
    fenster = []
    for minuten in fenster_minuten:
        grenze = jetzt - minuten * 60
        im_fenster = [a for a in anfragen if a["ende"] >= grenze]
        if not im_fenster:
            fenster.append({"minuten": minuten, "anfragen": 0, "spitze": 0,
                            "mittel": 0.0, "auslastung": 0.0,
                            "fehler": 0, "medianSekunden": 0.0})
            continue
        dauern = sorted(a["dauer"] for a in im_fenster)
        belegt = sum(dauern)
        spitze = _gleichzeitig(im_fenster)
        fenster.append({
            "minuten": minuten,
            "anfragen": len(im_fenster),
            "spitze": spitze,
            # Mittlere Slot-Belegung: Summe der Laufzeiten je Fensterlaenge.
            "mittel": round(belegt / (minuten * 60), 2),
            "auslastung": round(spitze / slots * 100, 1) if slots else 0.0,
            "fehler": sum(1 for a in im_fenster if a["status"] >= 400),
            "medianSekunden": round(dauern[len(dauern) // 2], 1),
            "laengsteSekunden": round(dauern[-1], 1),
        })

    return {
        "ok": True,
        "erkannt": len(anfragen),
        "slots": slots,
        "letzteAnfrage": datetime.fromtimestamp(jetzt).strftime("%Y-%m-%d %H:%M:%S"),
        "fenster": fenster,
    }
