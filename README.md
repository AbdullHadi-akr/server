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
  -e OLLAMA_URL=http://AZEU-DEW-DEVGPU-02:5020 \
  modell-portal
```

Danach im Browser: <http://localhost:5021> bzw. `http://<host>:5021`.

## Aktualisieren

Ein `docker compose up -d` allein baut das Image **nicht** neu – der Container
läuft dann weiter mit dem alten Stand und neue Seiten fehlen. Nach jedem
`git pull` daher:

```bash
git pull
docker compose up -d --build
```

Welcher Stand tatsächlich läuft, steht im Fuß jeder Seite und unter
<http://localhost:5021/healthz>.

## Konfiguration

Alles über Umgebungsvariablen:

| Variable            | Standard                            | Bedeutung |
|---------------------|-------------------------------------|-----------|
| `OLLAMA_URL`        | `http://AZEU-DEW-DEVGPU-02:5020`   | Adresse, unter der **das Portal** Ollama erreicht (für die Prüfungen). |
| `PUBLIC_OLLAMA_URL` | wie `OLLAMA_URL`                    | Adresse, die den Nutzern in der VS-Code-Konfiguration angezeigt wird. |
| `VENDOR_NAME`       | `A100`                              | Name des Anbieter-Eintrags und Suffix der Modellnamen. |
| `PORT` / `HOST`     | `5021` / `0.0.0.0`                  | Bindung des Portals. |
| `OLLAMA_CONTAINER`  | `ollama`                            | Name des Containers, in dem Ollama läuft. |
| `DOCKER_SOCKET`     | `/var/run/docker.sock`              | Pfad zum Docker-Socket. |
| `DOCKER_STEUERUNG`  | `true`                              | `false` = Betriebsseite nur lesend. |
| `STEUER_TOKEN`      | leer                                | Passwort für schreibende Aktionen. |
| `GPU_NAME`          | `NVIDIA A100`                       | Anzeigename der GPU. |
| `GPU_VRAM_GIB`      | `80`                                | VRAM der GPU für den Rechner. |
| `STANDARD_PARALLEL` | `4`                                 | Aktueller Wert von `OLLAMA_NUM_PARALLEL`. |
| `STANDARD_KONTEXT`  | `50000`                             | Aktueller Wert von `OLLAMA_CONTEXT_LENGTH`. |
| `PROBE_TIMEOUT`     | `10`                                | Timeout (s) für Erreichbarkeits-Prüfungen. |
| `CHAT_TIMEOUT`      | `300`                               | Timeout (s) für Testanfragen – großzügig wegen Kaltstart des Modells. |

Läuft Ollama auf dem Docker-Host selbst, ist
`OLLAMA_URL=http://host.docker.internal:5020` der richtige Wert (die
`extra_hosts`-Zeile in der `docker-compose.yml` ist dafür schon vorbereitet).

## Was das Portal prüft

Der Knopf **„Server prüfen“** testet der Reihe nach:

1. **Namensauflösung** – lässt sich der Hostname aus `OLLAMA_URL` im Container
   auflösen? (Der Container nutzt nicht zwingend denselben DNS wie dein PC.)
2. **TCP-Verbindung** – nimmt Port 5020 Verbindungen an? Trennt „Connection
   refused“ (Ollama lauscht nur auf 127.0.0.1) von „Timeout“ (Firewall).
3. `GET /api/version` – antwortet dort wirklich Ollama?
4. `GET /api/tags` – Liste der installierten Modelle.
5. Sind `qwen3:30b-a3b` und `qwen3-coder:30b` installiert?
6. `GET /v1/models` – steht der OpenAI-kompatible Endpunkt bereit? Genau den
   spricht VS Code über `apiType: "chat-completions"` an.

Jeder fehlgeschlagene Schritt nennt die konkrete Ursache samt Behebung; auf
einen Fehler folgende Schritte werden als „übersprungen“ markiert, statt
irreführende Folgefehler zu melden.

Der Knopf **„Modelle live testen“** schickt zusätzlich pro Modell eine echte
Anfrage an `POST /v1/chat/completions`, misst die Antwortzeit (und weist auf einen
Kaltstart hin) und prüft mit einem Beispiel-Werkzeug, ob **Tool Calling**
tatsächlich funktioniert – schlägt das fehl, sollte in der
`chatLanguageModels.json` `"toolCalling": false` gesetzt werden.

qwen3 ist ein Reasoning-Modell und schreibt seinen Gedankengang in
`<think>…</think>` vor die Antwort. Der Test unterdrückt das per `/no_think`,
entfernt verbliebene Denkblöcke aus der Antwort und gibt genug Token frei, damit
das Modell nicht mitten im Gedankengang abgeschnitten wird. Bleibt trotzdem kein
sichtbarer Text übrig, meldet das Portal eine **Warnung** statt eines Fehlers –
der Endpunkt funktioniert dann trotzdem. Dasselbe gilt für fehlendes Tool
Calling: eine Einschränkung, kein Ausfall.

## Betriebsseite (`/betrieb`)

Die zweite Seite des Portals steuert den Container, in dem Ollama läuft, und
legt Nutzeranzahl und Kontextlänge aus.

**Status und Steuerung** – Zustand, Laufzeit, Health, Image, Neustart-Regel,
GPU-Zuweisung, CPU-/RAM-Verbrauch und die gesetzten `OLLAMA_*`-Variablen. Dazu
Knöpfe für Neustart, Start, Stopp und die letzten Log-Zeilen. Zusätzlich zeigt
die Seite über `/api/ps`, welche Modelle gerade im GPU-Speicher liegen und wie
viel VRAM sie **tatsächlich** belegen – die Gegenprobe zur Schätzung.

**VRAM-Rechner** – Zwei Regler für Nutzeranzahl (`OLLAMA_NUM_PARALLEL`) und
Kontext je Nutzer (`OLLAMA_CONTEXT_LENGTH`), dazu KV-Cache-Datentyp und Anzahl
gleichzeitig geladener Modelle. Die Seite zeigt sofort den voraussichtlichen
Verbrauch, die Auslastung der GPU und – falls es nicht passt – wie viele Nutzer
bzw. wie viel Kontext stattdessen möglich wären.

```
VRAM = Gewichte + KV-Cache + Rechenpuffer
KV-Cache = 96 KiB/Token × Nutzeranzahl × Kontext × KV-Faktor
```

Die 96 KiB je Token folgen aus dem Aufbau von qwen3-30b-a3b: 2 (K und V) ×
4 KV-Heads × 128 Head-Dim × 48 Layer × 2 Byte (f16). Ollama legt pro parallelem
Slot einen eigenen KV-Cache an – der Kontext gilt also **je Nutzer**.
Gegenprobe mit den gemessenen Werten: 4 Nutzer × 50 000 Token ergeben
17,32 GiB Gewichte + 18,31 GiB KV + 1,40 GiB Puffer = **37,03 GiB**; gemessen
wurden 37 GiB. Beide Modelle gleichzeitig geladen belegen damit 74 GiB der
80 GiB einer A100.

**Einstellungen übernehmen** – Docker kann die Umgebung eines bestehenden
Containers nicht ändern. Das Portal stoppt den Container daher, benennt ihn als
Sicherung um (`ollama-vorher-<Zeitstempel>`) und legt ihn mit identischer
Konfiguration, aber neuen Werten neu an: Volumes, Portbindungen,
GPU-Zuweisung, Netzwerke, Labels und alle übrigen Umgebungsvariablen bleiben
erhalten, heruntergeladene Modelle also auch. Schlägt der Start fehl, wird der
alte Container automatisch zurückbenannt und wieder gestartet. Es wird immer
genau eine Sicherung aufbewahrt.

> **Bei Compose-verwalteten Containern:** Die Werte gelten sofort, werden aber
> vom nächsten `docker compose up` wieder aus der compose-Datei überschrieben.
> Die Seite weist darauf hin und nennt die einzutragenden Werte.

### Voraussetzungen und Sicherheit

Die Betriebsseite braucht den Docker-Socket:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
group_add:
  - "999"          # GID der Gruppe docker, ermitteln mit: getent group docker
```

Zugriff auf den Docker-Socket entspricht faktisch Root-Rechten auf dem Host.
Deshalb:

- Der Containername kommt ausschließlich aus `OLLAMA_CONTAINER`, nie aus der
  Anfrage des Browsers – über das Portal lässt sich kein anderer Container
  ansprechen.
- `DOCKER_STEUERUNG=false` schaltet alle schreibenden Aktionen ab; die Seite
  bleibt als reine Statusanzeige nutzbar.
- `STEUER_TOKEN=…` verlangt für Neustart und Einstellungsänderungen ein
  Passwort (Header `X-Portal-Token`, im Browser einmalig abgefragt).
- Ohne gemounteten Socket läuft das Portal normal weiter; die Betriebsseite
  erklärt dann, was fehlt.

## API

| Endpunkt                 | Zweck |
|--------------------------|-------|
| `GET /`                  | Portal-Seite mit Anleitung. |
| `GET /api/modelle`       | Modell-Metadaten und Endpunkt-Adressen. |
| `GET /api/vscode-config` | Fertiger Inhalt der `chatLanguageModels.json`. |
| `GET /api/diagnose`      | Vollständiger Selbsttest gegen Ollama. |
| `GET /api/test?model=…`  | Echte Chat- und Tool-Calling-Anfrage an ein Modell. |
| `GET /healthz`           | Healthcheck des Portals selbst. |
| `GET /betrieb`           | Betriebsseite. |
| `GET /api/geladen`       | Aktuell geladene Modelle samt echtem VRAM (`/api/ps`). |
| `GET /api/docker/status` | Zustand des Ollama-Containers. |
| `GET /api/docker/logs`   | Letzte Log-Zeilen (`?zeilen=300`). |
| `GET /api/vram`          | VRAM-Schätzung (`?parallel=…&kontext=…&kv=…&modelle=…`). |
| `POST /api/docker/aktion` | `{"aktion": "start"\|"stopp"\|"neustart"}` |
| `POST /api/docker/einstellungen` | `{"parallel": 4, "kontext": 50000, "kv": "f16"}` |

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
  server.py     HTTP-Server, Routen, Auslieferung der statischen Dateien
  ollama.py     Prüfungen gegen Ollama (Erreichbarkeit, Modelle, Chat, Tools)
  dockerctl.py  Docker-Engine-API über den Unix-Socket: Status, Neustart,
                Neuerstellen mit geänderter Umgebung inkl. Rollback
  vram.py       VRAM-Schätzung aus Nutzeranzahl, Kontext und KV-Cache-Typ
  config.py     Modelle, Endpunkte, Erzeugung der chatLanguageModels.json
  static/       index.html, betrieb.html, style.css, app.js, betrieb.js
Dockerfile
docker-compose.yml
```

Das Portal nutzt ausschließlich die Python-Standardbibliothek – der Image-Build
braucht daher keinen Zugriff auf PyPI.
