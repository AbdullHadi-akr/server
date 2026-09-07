# Modell-Portal – lokale Modelle in VS Code

Ein kleines Web-Portal im Docker-Container, das auf **Port 5021** läuft. Es erklärt
Schritt für Schritt, wie die lokal auf **Port 5020** unter Ollama laufenden Modelle
(`qwen3:30b-a3b` und `qwen3-coder:30b`) im VS-Code-Chat eingebunden werden, und
prüft auf Knopfdruck, ob Ollama korrekt läuft und die Modelle sauber antworten.

## Starten

```bash
docker compose up -d --build
# oder ohne Compose:
docker build -t modell-portal .
docker run -d --name modell-portal -p 5021:5021 \
  -e OLLAMA_URL=http://azeu-dew-devappl-01:5020 \
  modell-portal
```

Danach im Browser: <http://localhost:5021> bzw. `http://<host>:5021`.

## Konfiguration

Alles über Umgebungsvariablen:

| Variable            | Standard                            | Bedeutung |
|---------------------|-------------------------------------|-----------|
| `OLLAMA_URL`        | `http://azeu-dew-devappl-01:5020`   | Adresse, unter der **das Portal** Ollama erreicht (für die Prüfungen). |
| `PUBLIC_OLLAMA_URL` | wie `OLLAMA_URL`                    | Adresse, die den Nutzern in der VS-Code-Konfiguration angezeigt wird. |
| `VENDOR_NAME`       | `A100`                              | Name des Anbieter-Eintrags und Suffix der Modellnamen. |
| `PORT` / `HOST`     | `5021` / `0.0.0.0`                  | Bindung des Portals. |
| `PROBE_TIMEOUT`     | `10`                                | Timeout (s) für Erreichbarkeits-Prüfungen. |
| `CHAT_TIMEOUT`      | `300`                               | Timeout (s) für Testanfragen – großzügig wegen Kaltstart des Modells. |

Läuft Ollama auf dem Docker-Host selbst, ist
`OLLAMA_URL=http://host.docker.internal:5020` der richtige Wert (die
`extra_hosts`-Zeile in der `docker-compose.yml` ist dafür schon vorbereitet).

## Was das Portal prüft

Der Knopf **„Server prüfen“** testet der Reihe nach:

1. `GET /api/version` – ist Ollama überhaupt erreichbar?
2. `GET /api/tags` – Liste der installierten Modelle.
3. Sind `qwen3:30b-a3b` und `qwen3-coder:30b` installiert?
4. `GET /v1/models` – steht der OpenAI-kompatible Endpunkt bereit? Genau den
   spricht VS Code über `apiType: "chat-completions"` an.

Der Knopf **„Modelle live testen“** schickt zusätzlich pro Modell eine echte
Anfrage an `POST /v1/chat/completions`, misst die Antwortzeit (und weist auf einen
Kaltstart hin) und prüft mit einem Beispiel-Werkzeug, ob **Tool Calling**
tatsächlich funktioniert – schlägt das fehl, sollte in der
`chatLanguageModels.json` `"toolCalling": false` gesetzt werden.

## API

| Endpunkt                 | Zweck |
|--------------------------|-------|
| `GET /`                  | Portal-Seite mit Anleitung. |
| `GET /api/modelle`       | Modell-Metadaten und Endpunkt-Adressen. |
| `GET /api/vscode-config` | Fertiger Inhalt der `chatLanguageModels.json`. |
| `GET /api/diagnose`      | Vollständiger Selbsttest gegen Ollama. |
| `GET /api/test?model=…`  | Echte Chat- und Tool-Calling-Anfrage an ein Modell. |
| `GET /healthz`           | Healthcheck des Portals selbst. |

## Einrichtung in VS Code (Kurzfassung)

1. <kbd>Strg</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd> → **Chat: Manage Language Models**
2. **Add Models** → **Custom Endpoint**, dann mehrfach <kbd>Enter</kbd>, bis sich
   `chatLanguageModels.json` öffnet.
3. Das erzeugte Template löschen und den vom Portal angezeigten Inhalt einfügen
   (Kopieren-Knopf auf der Seite), speichern.
4. Im Chat das Modell `qwen3 (A100)` bzw. `qwen3-coder (A100)` wählen.

Die erste Antwort kann verzögert kommen, weil Ollama das Modell erst lädt; alle
weiteren Antworten kommen dann zügig.

## Aufbau

```
app/
  server.py    HTTP-Server, Routen, Auslieferung der statischen Dateien
  ollama.py    Prüfungen gegen Ollama (Erreichbarkeit, Modelle, Chat, Tools)
  config.py    Modelle, Endpunkte, Erzeugung der chatLanguageModels.json
  static/      index.html, style.css, app.js
Dockerfile
docker-compose.yml
```

Das Portal nutzt ausschließlich die Python-Standardbibliothek – der Image-Build
braucht daher keinen Zugriff auf PyPI.
