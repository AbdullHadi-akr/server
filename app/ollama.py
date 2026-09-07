"""Pruefungen gegen den Ollama-Server (nur Standardbibliothek)."""

import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config

# qwen3 ist ein Reasoning-Modell: es schreibt seinen Gedankengang in
# <think>...</think> vor die eigentliche Antwort. VS Code blendet das aus,
# fuer die Pruefung muss es entfernt werden.
DENKBLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


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
            return {"ok": False, "status": 200,
                    "fehler": f"Antwort von {url} ist kein JSON: {raw[:200]}",
                    "ms": dauer}
    except urllib.error.HTTPError as exc:
        dauer = round((time.monotonic() - started) * 1000)
        details = exc.read().decode("utf-8", "replace")[:300]
        return {"ok": False, "status": exc.code,
                "fehler": f"HTTP {exc.code} von {url}: {details or exc.reason}",
                "ms": dauer}
    except socket.timeout:
        dauer = round((time.monotonic() - started) * 1000)
        return {"ok": False, "status": 0,
                "fehler": f"Zeitueberschreitung nach {dauer // 1000} s bei {url}",
                "ms": dauer}
    except urllib.error.URLError as exc:
        dauer = round((time.monotonic() - started) * 1000)
        grund = exc.reason
        if isinstance(grund, socket.timeout):
            grund = f"Zeitueberschreitung nach {dauer // 1000} s"
        return {"ok": False, "status": 0,
                "fehler": f"Keine Verbindung zu {url} ({grund})", "ms": dauer}
    except Exception as exc:
        dauer = round((time.monotonic() - started) * 1000)
        return {"ok": False, "status": 0, "fehler": f"{type(exc).__name__}: {exc}",
                "ms": dauer}


# ---------------------------------------------------------------- Netzwerk
def _ziel():
    """Zerlegt OLLAMA_URL in Hostname und Port."""
    teile = urllib.parse.urlsplit(config.OLLAMA_URL)
    return teile.hostname or "", teile.port or (443 if teile.scheme == "https" else 80)


def _netz_schritte():
    """Prueft Namensaufloesung und TCP-Verbindung getrennt voneinander.

    Das trennt die drei Fehlerbilder, die im Container am haeufigsten
    auftreten: unbekannter Hostname, geschlossener Port, Paketfilter.
    """
    host, port = _ziel()
    schritte = []

    start = time.monotonic()
    try:
        adressen = sorted({eintrag[4][0] for eintrag in
                           socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)})
        dns_ok, dns_info = True, f"{host} -> {', '.join(adressen)}"
    except socket.gaierror as exc:
        dns_ok = False
        dns_info = f"Hostname '{host}' ist nicht aufloesbar ({exc.strerror or exc})"
    schritte.append({
        "id": "dns",
        "titel": "Namensaufloesung",
        "beschreibung": f"DNS-Abfrage fuer {host}",
        "ok": dns_ok,
        "ms": round((time.monotonic() - start) * 1000),
        "info": dns_info,
        "hilfe": ("Der Container nutzt nicht zwingend denselben DNS-Server wie dein "
                  "Arbeitsplatz. Abhilfe: OLLAMA_URL auf die IP-Adresse setzen, oder "
                  "in der docker-compose.yml einen extra_hosts-Eintrag ergaenzen. "
                  "Laeuft Ollama auf dem Docker-Host selbst, ist "
                  "http://host.docker.internal:5020 der richtige Wert."),
    })

    if not dns_ok:
        return schritte, False

    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=config.PROBE_TIMEOUT):
            tcp_ok, tcp_info = True, f"Port {port} auf {host} nimmt Verbindungen an"
    except socket.timeout:
        tcp_ok = False
        tcp_info = (f"Zeitueberschreitung auf {host}:{port} - meist eine Firewall, "
                    "die die Pakete verwirft")
    except OSError as exc:
        tcp_ok = False
        tcp_info = f"Port {port} auf {host} nicht erreichbar ({exc.strerror or exc})"
    schritte.append({
        "id": "tcp",
        "titel": "TCP-Verbindung",
        "beschreibung": f"Verbindungsaufbau zu {host}:{port}",
        "ok": tcp_ok,
        "ms": round((time.monotonic() - start) * 1000),
        "info": tcp_info,
        "hilfe": ("Ollama muss mit OLLAMA_HOST=0.0.0.0:5020 gestartet sein, sonst "
                  "lauscht der Dienst nur auf 127.0.0.1 und ist aus dem Container "
                  "nicht erreichbar. Pruefen auf dem Server: "
                  "'ss -tlnp | grep 5020'."),
    })
    return schritte, tcp_ok


# ---------------------------------------------------------------- Diagnose
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


def _uebersprungen(grund="Uebersprungen, weil eine vorherige Pruefung fehlschlug"):
    return {"ok": False, "ms": 0, "fehler": grund}


def diagnose():
    """Vollstaendiger Selbsttest: Netzwerk, Erreichbarkeit, Modelle, Endpunkt."""
    schritte, erreichbar = _netz_schritte()

    version = _request("GET", "/api/version") if erreichbar else _uebersprungen()
    schritte.append({
        "id": "erreichbar",
        "titel": "Ollama antwortet",
        "beschreibung": f"GET {config.OLLAMA_URL}/api/version",
        "ok": version["ok"],
        "ms": version["ms"],
        "info": (f"Ollama {version['body'].get('version', '?')}" if version["ok"]
                 else version.get("fehler", "")),
        "hilfe": ("Auf dem Port antwortet etwas, aber nicht wie Ollama. Laeuft dort "
                  "vielleicht ein anderer Dienst oder ein Reverse Proxy? "
                  "Status pruefen mit 'systemctl status ollama'."),
    })

    tags = _request("GET", "/api/tags") if version["ok"] else _uebersprungen()
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
            "info": ("gefunden" if da else
                     ("nicht in der Modellliste" if tags["ok"] else "nicht pruefbar")),
            "hilfe": f"Nachinstallieren mit 'ollama pull {modell['id']}'.",
        })

    openai = _request("GET", "/v1/models") if version["ok"] else _uebersprungen()
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


# ------------------------------------------------------------- Modelltests
def _nachricht(antwort):
    """Holt die Assistenten-Nachricht aus einer /v1-Antwort."""
    try:
        wahl = antwort["body"]["choices"][0]
        return wahl["message"], wahl.get("finish_reason", "")
    except (KeyError, IndexError, TypeError):
        return None, ""


def _sichtbarer_text(nachricht):
    """Antworttext ohne den Gedankengang des Reasoning-Modells."""
    inhalt = nachricht.get("content") or ""
    ohne_denken = DENKBLOCK.sub("", inhalt)
    # Ein unvollstaendiger Block (abgeschnitten) hinterlaest ein offenes <think>.
    ohne_denken = re.sub(r"<think>.*", "", ohne_denken, flags=re.DOTALL | re.IGNORECASE)
    return ohne_denken.strip()


def chat_test(model_id, tool_calling=False):
    """Schickt eine echte Anfrage an ein Modell und misst die Antwortzeit."""
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": "Antworte knapp und auf Deutsch."},
            # /no_think schaltet den Gedankengang von qwen3 ab. Aeltere Staende
            # ignorieren die Anweisung - dafuer wird <think> unten entfernt.
            {"role": "user", "content": "/no_think Antworte mit genau einem Wort: Bereit"},
        ],
        # Grosszuegig, damit ein denkendes Modell nicht mitten im
        # Gedankengang abgeschnitten wird und eine leere Antwort liefert.
        "max_tokens": 1024,
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

    nachricht, grund = _nachricht(antwort)
    if nachricht is None:
        ergebnis["ok"] = False
        ergebnis["fehler"] = ("Unerwartetes Antwortformat - der Endpunkt liefert kein "
                              "OpenAI-kompatibles JSON: "
                              + json.dumps(antwort["body"])[:200])
        return ergebnis

    text = _sichtbarer_text(nachricht)
    ergebnis["antwort"] = text[:300]
    ergebnis["denkmodus"] = "<think>" in (nachricht.get("content") or "").lower()
    if not text:
        # Antwort kam an, enthielt aber nur den Gedankengang. Der Endpunkt
        # funktioniert damit trotzdem - in VS Code ist das unproblematisch.
        ergebnis["hinweis"] = (
            "Das Modell hat nur seinen Gedankengang ausgegeben"
            + (" und wurde durch das Token-Limit abgeschnitten"
               if grund == "length" else "")
            + ". Der Endpunkt selbst funktioniert."
        )
        ergebnis["antwort"] = "(kein sichtbarer Text)"

    if tool_calling:
        ergebnis["tools"] = _tool_test(model_id)
    return ergebnis


def _tool_test(model_id):
    """Prueft, ob das Modell ueber den Endpunkt Werkzeuge aufrufen kann."""
    payload = {
        "model": model_id,
        "messages": [
            {"role": "user", "content": "/no_think Wie warm ist es gerade in Berlin?"},
        ],
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
        "max_tokens": 1024,
        "stream": False,
    }
    antwort = _request("POST", "/v1/chat/completions", payload, config.CHAT_TIMEOUT)
    if not antwort["ok"]:
        return {"ok": False, "ms": antwort["ms"],
                "fehler": antwort.get("fehler", "unbekannter Fehler")}

    nachricht, _ = _nachricht(antwort)
    if nachricht is None:
        return {"ok": False, "ms": antwort["ms"], "fehler": "Unerwartetes Antwortformat"}

    aufrufe = nachricht.get("tool_calls") or []
    if aufrufe:
        name = aufrufe[0].get("function", {}).get("name", "?")
        return {"ok": True, "ms": antwort["ms"], "info": f"Werkzeug '{name}' aufgerufen"}
    return {
        "ok": False,
        "ms": antwort["ms"],
        "fehler": ("Das Modell hat kein Werkzeug aufgerufen, sondern direkt geantwortet: "
                   + (_sichtbarer_text(nachricht)[:120] or "(kein Text)")
                   + ". Chat funktioniert normal; falls Agent-Aufrufe in VS Code "
                     "scheitern, in der chatLanguageModels.json "
                     "\"toolCalling\": false setzen."),
    }
