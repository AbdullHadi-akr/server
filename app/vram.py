"""Abschaetzung des VRAM-Bedarfs in Abhaengigkeit von Nutzerzahl und Kontext.

Der Speicherbedarf setzt sich aus drei Teilen zusammen:

    VRAM = Modellgewichte + KV-Cache + Rechenpuffer

Die Gewichte sind konstant, der KV-Cache waechst linear mit
OLLAMA_NUM_PARALLEL x OLLAMA_CONTEXT_LENGTH. Ollama legt pro paralleler
Anfrage einen eigenen Kontext-Slot an - der eingestellte Kontext gilt also
je Nutzer, nicht insgesamt.

KV-Cache je Token = 2 (K und V) x KV-Heads x Head-Dim x Layer x Bytes/Wert
Fuer qwen3-30b-a3b: 2 x 4 x 128 x 48 x 2 = 98304 Bytes = 96 KiB je Token.

Gegenprobe mit den gemessenen Werten (4 Nutzer, 50000 Kontext, f16):
    17,32 GiB Gewichte + 18,31 GiB KV + 1,40 GiB Puffer = 37,03 GiB
Gemessen wurden 37 GiB.
"""

GIB = 1024 ** 3

# KV-Cache-Datentyp (OLLAMA_KV_CACHE_TYPE) und sein Speicherfaktor.
KV_TYPEN = {
    "f16": {"faktor": 1.0, "name": "f16", "hinweis": "Standard, hoechste Qualitaet"},
    "q8_0": {"faktor": 0.5, "name": "q8_0",
             "hinweis": "halber KV-Speicher, Qualitaetsverlust kaum messbar"},
    "q4_0": {"faktor": 0.25, "name": "q4_0",
             "hinweis": "viertel KV-Speicher, spuerbarer Qualitaetsverlust"},
}

# Kennzahlen der Modelle. kv_pro_token gilt fuer f16.
MODELLE = {
    "qwen3:30b-a3b": {
        "gewichte_gib": 18.6e9 / GIB,   # Q4_K_M, laut 'ollama list' 18,6 GB
        "kv_pro_token": 98304,          # 48 Layer, 4 KV-Heads, Head-Dim 128
        "layer": 48,
    },
    "qwen3-coder:30b": {
        "gewichte_gib": 18.6e9 / GIB,
        "kv_pro_token": 98304,
        "layer": 48,
    },
}

# Grenzen fuer die Eingaben aus dem Portal.
MAX_PARALLEL = 64
MAX_KONTEXT = 262144
MIN_KONTEXT = 512


def _rechenpuffer_gib(parallel):
    """Rechen- und Graph-Puffer von llama.cpp, grob linear in der Slot-Zahl."""
    return 0.6 + 0.2 * parallel


def schaetzung(model_id, parallel, kontext, kv_typ="f16"):
    """VRAM-Bedarf eines einzelnen Modells."""
    spez = MODELLE[model_id]
    faktor = KV_TYPEN[kv_typ]["faktor"]
    kv_gib = spez["kv_pro_token"] * faktor * parallel * kontext / GIB
    gewichte = spez["gewichte_gib"]
    puffer = _rechenpuffer_gib(parallel)
    return {
        "model": model_id,
        "gewichteGib": round(gewichte, 2),
        "kvGib": round(kv_gib, 2),
        "pufferGib": round(puffer, 2),
        "gesamtGib": round(gewichte + kv_gib + puffer, 2),
        "kvProTokenKib": round(spez["kv_pro_token"] * faktor / 1024, 1),
    }


def max_parallel(model_id, kontext, vram_gib, kv_typ="f16", modelle_gleichzeitig=1):
    """Wie viele Nutzer passen bei diesem Kontext noch in den Speicher?"""
    spez = MODELLE[model_id]
    faktor = KV_TYPEN[kv_typ]["faktor"]
    for n in range(MAX_PARALLEL, 0, -1):
        bedarf = modelle_gleichzeitig * (
            spez["gewichte_gib"]
            + spez["kv_pro_token"] * faktor * n * kontext / GIB
            + _rechenpuffer_gib(n)
        )
        if bedarf <= vram_gib:
            return n
    return 0


def max_kontext(model_id, parallel, vram_gib, kv_typ="f16", modelle_gleichzeitig=1):
    """Groesster Kontext je Nutzer, der bei dieser Nutzerzahl noch passt."""
    spez = MODELLE[model_id]
    faktor = KV_TYPEN[kv_typ]["faktor"]
    frei = (vram_gib / modelle_gleichzeitig
            - spez["gewichte_gib"] - _rechenpuffer_gib(parallel))
    if frei <= 0 or parallel <= 0:
        return 0
    tokens = frei * GIB / (spez["kv_pro_token"] * faktor * parallel)
    return min(MAX_KONTEXT, int(tokens // 1024) * 1024)


def pruefe_eingaben(parallel, kontext, kv_typ):
    """Validiert die Eingaben und liefert eine Fehlermeldung oder None."""
    if not isinstance(parallel, int) or not 1 <= parallel <= MAX_PARALLEL:
        return f"Nutzeranzahl muss zwischen 1 und {MAX_PARALLEL} liegen."
    if not isinstance(kontext, int) or not MIN_KONTEXT <= kontext <= MAX_KONTEXT:
        return f"Kontext muss zwischen {MIN_KONTEXT} und {MAX_KONTEXT} Token liegen."
    if kv_typ not in KV_TYPEN:
        return f"Unbekannter KV-Cache-Typ: {kv_typ}"
    return None


def uebersicht(parallel, kontext, kv_typ, vram_gib, modelle_gleichzeitig):
    """Gesamtbild fuer die Portal-Seite: pro Modell und in Summe."""
    einzeln = [schaetzung(mid, parallel, kontext, kv_typ) for mid in MODELLE]
    # Alle gleichzeitig geladenen Modelle belegen den Speicher zusammen.
    schwerstes = max(einzeln, key=lambda e: e["gesamtGib"])
    summe = round(schwerstes["gesamtGib"] * modelle_gleichzeitig, 2)
    return {
        "parallel": parallel,
        "kontext": kontext,
        "kvTyp": kv_typ,
        "kvHinweis": KV_TYPEN[kv_typ]["hinweis"],
        "vramGib": vram_gib,
        "modelleGleichzeitig": modelle_gleichzeitig,
        "proModell": einzeln,
        "summeGib": summe,
        "auslastung": round(summe / vram_gib * 100, 1) if vram_gib else 0,
        "passt": summe <= vram_gib,
        "reserveGib": round(vram_gib - summe, 2),
        "maxParallel": max_parallel(schwerstes["model"], kontext, vram_gib, kv_typ,
                                    modelle_gleichzeitig),
        "maxKontext": max_kontext(schwerstes["model"], parallel, vram_gib, kv_typ,
                                  modelle_gleichzeitig),
        "gesamtkontext": parallel * kontext,
    }
