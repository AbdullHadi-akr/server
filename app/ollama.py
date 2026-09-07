"""Pruefungen gegen den Ollama-Server (nur Standardbibliothek)."""

import json
import time
import urllib.error
import urllib.request

from . import config


def _request(method, path, payload=None, timeout=None):
    """Fuehrt einen HTTP-Aufruf gegen Ollama aus und misst die Dauer."""
    url = f"{config.OLLAMA_URL}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.monotonic()
    try:
        # Kein Proxy verwenden: Ollama liegt im internen Netz.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout or config.PROBE_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
        dauer = round((time.monotonic() - started) * 1000)
        try:
            return {"ok": True, "status": 200, "body": json.loads(raw), "ms": dauer}
        except json.JSONDecodeError:
            return {"ok": False, "status": 200, "fehler": "Antwort ist kein JSON",
                    "body": raw[:500], "ms": dauer}
    except urllib.error.HTTPError as exc:
        dauer = round((time.monotonic() - started) * 1000)
        details = exc.read().decode("utf-8", "replace")[:500]
        return {"ok": False, "status": exc.code,
                "fehler": f"HTTP {exc.code}: {details or exc.reason}", "ms": dauer}
    except urllib.error.URLError as exc:
        dauer = round((time.monotonic() - started) * 1000)
        return {"ok": False, "status": 0,
                "fehler": f"Keine Verbindung zu {url} ({exc.reason})", "ms": dauer}
    except Exception as exc:  # z. B. Timeout
        dauer = round((time.monotonic() - started) * 1000)
        return {"ok": False, "status": 0, "fehler": f"{type(exc).__name__}: {exc}",
                "ms": dauer}


def _installierte_modelle(tags_body):
    namen = []
    for eintrag in (tags_body or {}).get("models", []):
        name = eintrag.get("model") or eintrag.get("name")
        if name:
            namen.append(name)
    return namen


def _ist_installiert(model_id, vorhanden):
    if model_id in vorhanden:
        return True
    # Ollama meldet Modelle ohne Tag gelegentlich als "<name>:latest".
    basis = model_id.split(":")[0]
    return any(n == model_id or n.split(":")[0] == basis for n in vorhanden)


def diagnose():
    """Vollstaendiger Selbsttest: Erreichbarkeit, Modelle, OpenAI-Endpunkt."""
    schritte = []

    version = _request("GET", "/api/version")
    schritte.append({
        "id": "erreichbar",
        "titel": "Ollama erreichbar",
        "beschreibung": f"GET {config.OLLAMA_URL}/api/version",
        "ok": version["ok"],
        "ms": version["ms"],
        "info": (f"Ollama {version['body'].get('version', '?')}" if version["ok"]
                 else version.get("fehler", "")),
        "hilfe": ("Laeuft der Dienst? Pruefen mit 'systemctl status ollama'. "
                  "Ollama muss mit OLLAMA_HOST=0.0.0.0:5020 gestartet sein, damit "
                  "er nicht nur auf localhost lauscht."),
    })

    tags = _request("GET", "/api/tags") if version["ok"] else {"ok": False, "ms": 0,
                                                               "fehler": "uebersprungen"}
    vorhanden = _installierte_modelle(tags.get("body")) if tags["ok"] else []
    schritte.append({
        "id": "modellliste",
        "titel": "Modellliste abrufbar",
        "beschreibung": f"GET {config.OLLAMA_URL}/api/tags",
        "ok": tags["ok"],
        "ms": tags["ms"],
        "info": (f"{len(vorhanden)} Modelle installiert: {', '.join(vorhanden) or '-'}"
                 if tags["ok"] else tags.get("fehler", "")),
        "hilfe": "Modelle listen mit 'ollama list'.",
    })

    for modell in config.MODELS:
        da = _ist_installiert(modell["id"], vorhanden)
        schritte.append({
            "id": f"modell:{modell['id']}",
            "titel": f"Modell {modell['id']} installiert",
            "beschreibung": "Abgleich mit der Ollama-Modellliste",
            "ok": da,
            "ms": 0,
            "info": "gefunden" if da else "nicht installiert",
            "hilfe": f"Nachinstallieren mit 'ollama pull {modell['id']}'.",
        })

    openai = (_request("GET", "/v1/models") if version["ok"]
              else {"ok": False, "ms": 0, "fehler": "uebersprungen"})
    schritte.append({
        "id": "openai",
        "titel": "OpenAI-kompatibler Endpunkt",
        "beschreibung": f"GET {config.OLLAMA_URL}/v1/models",
        "ok": openai["ok"],
        "ms": openai["ms"],
        "info": ("/v1/chat/completions steht bereit - genau diesen Pfad nutzt VS Code"
                 if openai["ok"] else openai.get("fehler", "")),
        "hilfe": ("Der OpenAI-Modus ist ab Ollama 0.1.24 enthalten. "
                  "Aeltere Version bitte aktualisieren."),
    })

    return {
        "ollamaUrl": config.OLLAMA_URL,
        "publicUrl": config.PUBLIC_OLLAMA_URL,
        "ok": all(s["ok"] for s in schritte),
        "schritte": schritte,
        "installiert": vorhanden,
        "zeitpunkt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def chat_test(model_id, tool_calling=False):
    """Schickt eine echte Anfrage an ein Modell und misst die Antwortzeit."""
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": "Antworte knapp und auf Deutsch."},
            {"role": "user", "content": "Antworte mit genau einem Wort: Bereit"},
        ],
        "max_tokens": 64,
        "stream": False,
    }
    antwort = _request("POST", "/v1/chat/completions", payload, config.CHAT_TIMEOUT)
    ergebnis = {
        "model": model_id,
        "ok": antwort["ok"],
        "ms": antwort["ms"],
        "kalt": antwort["ms"] > 15000,
    }
    if not antwort["ok"]:
        ergebnis["fehler"] = antwort.get("fehler", "unbekannter Fehler")
        return ergebnis

    try:
        nachricht = antwort["body"]["choices"][0]["message"]
        ergebnis["antwort"] = (nachricht.get("content") or "").strip()[:300]
    except (KeyError, IndexError, TypeError):
        ergebnis["ok"] = False
        ergebnis["fehler"] = "Unerwartetes Antwortformat"
        return ergebnis

    if tool_calling:
        ergebnis["tools"] = _tool_test(model_id)
    return ergebnis


def _tool_test(model_id):
    """Prueft, ob das Modell ueber den Endpunkt Werkzeuge aufrufen kann."""
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Wie warm ist es gerade in Berlin?"}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Liefert das aktuelle Wetter fuer eine Stadt.",
                "parameters": {
                    "type": "object",
                    "properties": {"stadt": {"type": "string"}},
                    "required": ["stadt"],
                },
            },
        }],
        "stream": False,
    }
    antwort = _request("POST", "/v1/chat/completions", payload, config.CHAT_TIMEOUT)
    if not antwort["ok"]:
        return {"ok": False, "ms": antwort["ms"],
                "fehler": antwort.get("fehler", "unbekannter Fehler")}
    try:
        nachricht = antwort["body"]["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return {"ok": False, "ms": antwort["ms"], "fehler": "Unerwartetes Antwortformat"}

    aufrufe = nachricht.get("tool_calls") or []
    if aufrufe:
        name = aufrufe[0].get("function", {}).get("name", "?")
        return {"ok": True, "ms": antwort["ms"], "info": f"Werkzeug '{name}' aufgerufen"}
    return {
        "ok": False,
        "ms": antwort["ms"],
        "fehler": ("Das Modell hat kein Werkzeug aufgerufen, sondern nur geantwortet. "
                   "In der chatLanguageModels.json ggf. \"toolCalling\": false setzen."),
    }
