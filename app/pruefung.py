"""Plausibilitaetspruefung von Konfiguration und Messwerten.

Widersprueche zwischen der VS-Code-Konfiguration, den Umgebungsvariablen des
Ollama-Containers und dem tatsaechlich vorhandenen Speicher fallen im Betrieb
sonst niemandem auf - sie aeussern sich nur in abgeschnittenen Antworten oder
ploetzlicher Langsamkeit. Hier werden sie benannt.
"""

import socket
import urllib.parse

from . import config, vram

WARNUNG = "warnung"
HINWEIS = "hinweis"


def _eintrag(stufe, titel, text, abhilfe=""):
    return {"stufe": stufe, "titel": titel, "text": text, "abhilfe": abhilfe}


def _tsd(zahl):
    """Tausenderpunkte, ohne die Satzzeichen des Textes anzutasten."""
    return f"{int(zahl):,}".replace(",", ".")


def _zahl(wert, ersatz=0):
    try:
        return int(wert)
    except (TypeError, ValueError):
        return ersatz


def _kontext_pruefen(kontext):
    """Vergleicht die Angaben der VS-Code-Konfiguration mit dem Slot-Kontext."""
    hinweise = []
    if not kontext:
        return hinweise
    for modell in config.MODELS:
        eingabe = modell["maxInputTokens"]
        ausgabe = modell["maxOutputTokens"]
        if eingabe > kontext:
            hinweise.append(_eintrag(
                WARNUNG,
                f"{modell['id']}: maxInputTokens groesser als der Kontext",
                f"In der chatLanguageModels.json stehen {_tsd(eingabe)} Token "
                f"Eingabe, ein Slot fasst aber nur {_tsd(kontext)} Token. "
                "VS Code darf damit mehr senden, als Ollama verarbeiten kann - "
                "der Anfang der Unterhaltung wird stillschweigend "
                "abgeschnitten.",
                f"maxInputTokens auf hoechstens {_tsd(max(0, kontext - ausgabe))} "
                "senken oder OLLAMA_CONTEXT_LENGTH erhoehen."))
        elif eingabe + ausgabe > kontext:
            hinweise.append(_eintrag(
                HINWEIS,
                f"{modell['id']}: Eingabe und Ausgabe zusammen zu gross",
                f"{_tsd(eingabe)} Token Eingabe und {_tsd(ausgabe)} Token "
                f"Ausgabe ergeben mehr als die {_tsd(kontext)} Token eines "
                "Slots. Bei langen Unterhaltungen bleibt kein Platz fuer die "
                "volle Antwort.",
                f"maxInputTokens auf {_tsd(max(0, kontext - ausgabe))} setzen."))
    return hinweise


def _speicher_pruefen(parallel, kontext, kv_typ, geladen, gpu_daten):
    hinweise = []
    vram_gib = gpu_daten.get("vramGib") or config.GPU_VRAM_GIB
    anzahl = len(geladen.get("modelle", [])) or 1

    if parallel and kontext:
        rechnung = vram.uebersicht(parallel, kontext, kv_typ, vram_gib, min(anzahl, 2))
        if not rechnung["passt"]:
            hinweise.append(_eintrag(
                WARNUNG,
                "Rechnerisch passt die Belegung nicht in den Speicher",
                f"{parallel} Slots mit je {_tsd(kontext)} Token brauchen fuer "
                f"{anzahl} Modell(e) etwa {rechnung['summeGib']} GiB, "
                f"verfuegbar sind {vram_gib} GiB.",
                f"Hoechstens {rechnung['maxParallel']} Nutzer oder "
                f"{_tsd(rechnung['maxKontext'])} Token Kontext, oder den "
                "KV-Cache auf q8_0 stellen - das halbiert ihn."))

    for modell in geladen.get("modelle", []):
        if not modell.get("nurGpu"):
            hinweise.append(_eintrag(
                WARNUNG,
                f"{modell['name']} liegt nur teilweise auf der GPU",
                f"Von {modell['gesamtGib']} GiB liegen nur "
                f"{modell['vramGib']} GiB im GPU-Speicher, der Rest im "
                "Arbeitsspeicher. Antworten werden dadurch um ein Vielfaches "
                "langsamer.",
                "Kontext oder Nutzeranzahl senken, den KV-Cache quantisieren "
                "oder weniger Modelle gleichzeitig geladen halten."))
    return hinweise


def _umgebung_pruefen(umgebung):
    hinweise = []
    kv_typ = (umgebung.get("OLLAMA_KV_CACHE_TYPE") or "").strip()
    flash = (umgebung.get("OLLAMA_FLASH_ATTENTION") or "").strip().lower()
    if kv_typ and kv_typ != "f16" and flash not in ("1", "true", "on"):
        hinweise.append(_eintrag(
            HINWEIS,
            "Quantisierter KV-Cache ohne Flash Attention",
            f"OLLAMA_KV_CACHE_TYPE steht auf {kv_typ}, "
            "OLLAMA_FLASH_ATTENTION ist aber nicht gesetzt. Aeltere "
            "Ollama-Staende ignorieren die Quantisierung dann - der Cache "
            "belegt weiter den vollen Speicher.",
            "OLLAMA_FLASH_ATTENTION=1 im Ollama-Container setzen."))

    if not (umgebung.get("OLLAMA_CONTEXT_LENGTH") or "").strip():
        hinweise.append(_eintrag(
            HINWEIS,
            "OLLAMA_CONTEXT_LENGTH ist nicht gesetzt",
            "Ollama verwendet dann seinen eigenen Standard. Der ist deutlich "
            "kleiner als das, was in der VS-Code-Konfiguration steht.",
            "Den Wert auf der Einstellungsseite setzen."))
    return hinweise


def _adresse_pruefen():
    """Prueft, ob der den Nutzern angezeigte Name aufloesbar ist."""
    teile = urllib.parse.urlsplit(config.PUBLIC_OLLAMA_URL)
    host = teile.hostname or ""
    if not host:
        return []
    try:
        socket.getaddrinfo(host, teile.port or 80, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return [_eintrag(
            HINWEIS,
            "Angezeigte Adresse ist vom Portal aus nicht aufloesbar",
            f"Die Nutzer sollen {config.PUBLIC_OLLAMA_URL} eintragen, dieser "
            "Name laesst sich vom Portal aus aber nicht aufloesen. Das kann "
            "richtig sein, wenn die Arbeitsplaetze einen anderen DNS nutzen - "
            "sonst traegt niemand eine funktionierende Adresse ein.",
            "PUBLIC_OLLAMA_URL pruefen.")]
    return []


def hinweise(zustand, geladen, gpu_daten):
    """Sammelt alle Hinweise. Leere Liste heisst: nichts Auffaelliges."""
    umgebung = (zustand or {}).get("einstellungen", {}) or {}
    parallel = _zahl(umgebung.get("OLLAMA_NUM_PARALLEL"), config.STANDARD_PARALLEL)
    kontext = _zahl(umgebung.get("OLLAMA_CONTEXT_LENGTH"), config.STANDARD_KONTEXT)
    kv_typ = (umgebung.get("OLLAMA_KV_CACHE_TYPE") or "f16").strip()
    if kv_typ not in vram.KV_TYPEN:
        kv_typ = "f16"

    gesammelt = []
    gesammelt += _kontext_pruefen(kontext)
    gesammelt += _speicher_pruefen(parallel, kontext, kv_typ, geladen or {},
                                   gpu_daten or {})
    gesammelt += _umgebung_pruefen(umgebung)
    gesammelt += _adresse_pruefen()

    return {
        "ok": True,
        "hinweise": gesammelt,
        "warnungen": sum(1 for h in gesammelt if h["stufe"] == WARNUNG),
        "geprueft": {
            "parallel": parallel,
            "kontext": kontext,
            "kvTyp": kv_typ,
            "vramGib": (gpu_daten or {}).get("vramGib") or config.GPU_VRAM_GIB,
            "gemessen": bool((gpu_daten or {}).get("gemessen")),
        },
    }
