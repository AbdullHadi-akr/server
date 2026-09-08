# Modell-Portal – lokale Modelle in VS Code

Ein kleines Web-Portal im Docker-Container, das auf **Port 5021** läuft. Es erklärt
Schritt für Schritt, wie die lokal auf **Port 5020** unter Ollama laufenden Modelle
(`qwen3:30b-a3b` und `qwen3-coder:30b`) im VS-Code-Chat eingebunden werden, und
prüft auf Knopfdruck, ob Ollama korrekt läuft und die Modelle sauber antworten.

## Die drei Seiten

| Seite | Zugang | Inhalt |
|-------|--------|--------|
| `/` | offen | Anleitung zur Einbindung in VS Code, Funktionsprüfung |
| `/uebersicht` | offen, nur lesend | Dienst-Status, GPU, Modelle, Slot-Auslastung |
| `/verlauf` | offen, nur lesend | Auslastung, Speicher und Anfragen über Tage und Wochen |
| `/betrieb` | **Passwort** | Neustart des Containers, Nutzeranzahl und Kontext ändern |

## Starten

```bash
docker compose up -d --build
# oder ohne Compose:
docker build -t modell-portal .
docker run -d --name modell-portal -p 5021:5021 \
  -e OLLAMA_URL=http://AZEU-DEW-DEVGPU-02:5020 \
  -e PUBLIC_OLLAMA_URL=http://azeu-dew-devappl-01:5021 \
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
| `OLLAMA_URL`        | `http://AZEU-DEW-DEVGPU-02:5020`    | Adresse, unter der **das Portal** Ollama erreicht: Prüfungen, Modelltests, Status, Auslastung. |
| `PUBLIC_OLLAMA_URL` | `http://azeu-dew-devappl-01:5021`   | Adresse, die den **Nutzern** angezeigt wird – das Portal selbst. |
| `ALT_OLLAMA_URL`    | `http://azeu-dew-devappl-01:5020`   | Vorherige Adresse, nur für den Umstellungshinweis. Leer = kein Hinweis. |
| `VENDOR_NAME`       | `A100`                              | Name des Anbieter-Eintrags und Suffix der Modellnamen. |
| `PORT` / `HOST`     | `5021` / `0.0.0.0`                  | Bindung des Portals. |
| `OLLAMA_CONTAINER`  | `ollama`                            | Name des Containers, in dem Ollama läuft. |
| `DOCKER_SOCKET`     | `/var/run/docker.sock`              | Pfad zum Docker-Socket. |
| `DOCKER_STEUERUNG`  | `true`                              | `false` = Betriebsseite nur lesend. |
| `PORTAL_PASSWORT`   | leer                                | Passwort fest vorgeben statt Ersteinrichtung. |
| `DATEN_VERZEICHNIS` | `/data`                             | Ablage des Passwort-Hashes. |
| `SITZUNGSDAUER`     | `28800`                             | Gültigkeit einer Anmeldung in Sekunden. |
| `LOG_ZEILEN`        | `4000`                              | Log-Zeilen für die Auslastungsanalyse. |
| `VERLAUF_AKTIV`     | `true`                              | Aufzeichnung des Verlaufs. |
| `VERLAUF_TAKT`      | `60`                                | Sekunden zwischen zwei Messpunkten. |
| `VERLAUF_TAGE`      | `30`                                | Aufbewahrung der Messpunkte. |
| `PROXY_AKTIV`       | `true`                              | Proxy vor Ollama. |
| `PROXY_PORT`        | wie `PORT`                          | Abweichender Wert startet einen zweiten Listener. |
| `GPU_NAME`          | `NVIDIA A100`                       | Anzeigename der GPU. |
| `GPU_VRAM_GIB`      | `80`                                | Rückfallwert, falls `nvidia-smi` nicht erreichbar ist. |
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
  - "115"          # GID der Gruppe docker, ermitteln mit: getent group docker
```

Zugriff auf den Docker-Socket entspricht faktisch Root-Rechten auf dem Host.
Deshalb:

- Der Containername kommt ausschließlich aus `OLLAMA_CONTAINER`, nie aus der
  Anfrage des Browsers – über das Portal lässt sich kein anderer Container
  ansprechen.
- `DOCKER_STEUERUNG=false` schaltet alle schreibenden Aktionen ab; die Seite
  bleibt als reine Statusanzeige nutzbar.
- Die Einstellungsseite ist passwortgeschützt (siehe unten).
- Ohne gemounteten Socket läuft das Portal normal weiter; die Seiten erklären
  dann, was fehlt.

## Übersichtsseite (`/uebersicht`)

Ohne Anmeldung erreichbar und rein lesend – gedacht für alle, die nur wissen
wollen, ob der Dienst läuft und wie ausgelastet er ist. Aktualisiert sich alle
20 Sekunden und zeigt:

- **Dienst** – Container-Zustand, Laufzeit, GPU-Zuweisung, konfigurierte Slots
  und Kontextlänge, CPU- und RAM-Verbrauch.
- **GPU** – die echten Werte der Karte, über `nvidia-smi` im Ollama-Container
  gemessen: belegter und freier VRAM, Auslastung, Temperatur, Leistungsaufnahme.
  Darunter, was davon auf Ollama entfällt (`/api/ps`) neben dem rechnerisch
  erwarteten Wert. Ist `nvidia-smi` nicht erreichbar, sagt die Seite das und der
  Rechner nutzt weiter den konfigurierten Wert `GPU_VRAM_GIB`.
- **Hinweise** – Widersprüche zwischen VS-Code-Konfiguration, Container-Umgebung
  und vorhandenem Speicher (siehe unten).
- **Modelle und Slots** – je geladenem Modell der belegte VRAM, die Anzahl
  Slots mit ihrem Kontext, der Gesamtkontext und bis wann Ollama das Modell
  bereithält. Liegt ein Modell nur teilweise auf der GPU, wird das markiert.
- **Slot-Auslastung** – live und im Rückblick, mit Knopf zum sofortigen
  Neuladen und abschaltbarer Aktualisierung alle 10 Sekunden.

### Wie die Slot-Auslastung gemessen wird

Ollama bietet keine Schnittstelle für belegte Slots. Das Portal misst daher
auf zwei voneinander unabhängigen Wegen:

**Gesamtzahl der Slots.** `OLLAMA_NUM_PARALLEL` gilt **je Modell** – Ollama
hält für jedes geladene Modell einen eigenen Satz Slots vor. Bei 4 parallelen
Anfragen und zwei geladenen Modellen sind es also 8 Slots. Die Übersicht rechnet
entsprechend und schreibt die Herleitung dazu.

**Live – gerade aktive Sitzungen.** Das Portal liest über den Docker-Socket
`/proc/net/tcp` *im Ollama-Container* und zählt die hergestellten Verbindungen
auf dessen Port. Angezeigt wird das als Slot-Leiste („aktiv“ / „frei“); mehr
Sitzungen als Slots werden als wartend markiert. Eigene Statusabfragen des
Portals rechnet es anhand seiner eigenen Adresse heraus, `LISTEN`- und
`TIME_WAIT`-Einträge zählen nicht mit.

> VS Code hält je laufendem Chat eine Verbindung offen. Nach einer Antwort
> kann sie durch Keep-Alive noch kurz bestehen bleiben – kurzzeitig kann die
> Anzeige daher etwas höher liegen als die Zahl der wirklich rechnenden
> Anfragen. Und eine Verbindung verrät nicht, welches Modell sie nutzt: Die
> Zahl gilt für alle geladenen Modelle zusammen, nicht je Modell.

**Rückblick – die letzten 15 und 60 Minuten.** Aus dem GIN-Zugriffslog des
Containers (Endzeitpunkt und Dauer je Anfrage) rekonstruiert das Portal das
Zeitfenster jeder Anfrage und ermittelt per Sweep-Line die höchste
gleichzeitige Belegung, dazu Anzahl, mittlere Belegung, Median- und
Maximaldauer sowie Fehler.

> Eine Logzeile entsteht erst, wenn die Anfrage **beantwortet** ist. Laufende
> Sitzungen stehen deshalb ausschließlich in der Live-Anzeige – genau deshalb
> gibt es beide Messungen. Und da das Zugriffslog das Modell nicht mitschreibt,
> gilt der Rückblick für den Ollama-Dienst insgesamt.

Ist die Live-Messung nicht möglich (kein Docker-Socket, `exec` untersagt), sagt
die Seite das und der Rückblick funktioniert unabhängig davon weiter.

## Proxy-Modus – exakte Slots je Modell

Weder die Ollama-API noch das Zugriffslog verraten, welches Modell eine gerade
laufende Anfrage belegt. Wer den Verkehr durch das Portal leitet, bekommt genau
das.

Der Proxy hängt **am selben Port wie das Portal** (5021): Was keine Portal-Route
und keine statische Datei ist, geht an Ollama weiter. Das geht auf, weil sich die
Pfade nicht überschneiden – das Portal benennt seine Endpunkte deutsch
(`/api/nutzung`, `/api/verlauf`, `/api/geladen` …), Ollama englisch (`/api/chat`,
`/api/tags`, `/api/ps` …). **Wer neue Portal-Endpunkte ergänzt, muss diese
Trennung wahren.** So genügt ein einziger offener Port für Portal und Modelle.

Er reicht alle Pfade und Methoden weiter, liest den Anfragerumpf (dort steht das
Modell) und gibt die Antwort **ungepuffert** zurück, damit der Chat in VS Code
weiter Wort für Wort erscheint. Daraus entsteht je Modell: laufende Anfragen,
davon rechnend (bis `OLLAMA_NUM_PARALLEL`) und wartend. Die Übersicht zeigt das
auf den Modellkarten, der Verlauf schreibt es mit.

Ist eine strikte Trennung gewünscht, startet ein abweichender `PROXY_PORT` einen
zweiten Listener auf eigenem Port; der muss dann zusätzlich veröffentlicht werden.

**Der Proxy ist in Betrieb.** `PUBLIC_OLLAMA_URL` zeigt auf
`http://azeu-dew-devappl-01:5021` – dieselbe Adresse wie das Portal selbst. Wer seine `chatLanguageModels.json` vor der Umstellung angelegt
hat, muss die `url` bei beiden Modellen einmalig ändern – die Seite weist mit
einem Hinweis darauf hin und nennt beide Adressen. Die alte Adresse (Port 5020)
funktioniert weiter, liefert aber keine Zahlen je Modell.

**Reihenfolge beim Ausrollen:** erst `docker compose up -d --build`, dann von
einem Arbeitsplatz aus `curl http://azeu-dew-devappl-01:5021/api/version`
gegenprüfen – kommt die Ollama-Version zurück, reicht das Portal korrekt durch –
und **erst danach** die Nutzer bitten, umzustellen. Ein zusätzlicher Port in der
Firewall ist nicht nötig: Port 5021 war für die Portalseite ohnehin offen.

**Was das kostet:** Das Portal ist damit im kritischen Pfad – ist es aus,
funktioniert für umgestellte Nutzer kein Chat mehr. Rückweg: `PROXY_AKTIV=false`
und `PUBLIC_OLLAMA_URL` zurück auf `http://azeu-dew-devappl-01:5020`. Da das
Portal die Anfragen nur weiterreicht, ist der direkte Weg über Port 5020
jederzeit parallel nutzbar. Die
Plausibilitätsprüfung **warnt**, wenn die angezeigte Adresse auf den Proxy-Port
zeigt, der Proxy aber abgeschaltet ist – der wahrscheinlichste Bedienfehler nach
der Umstellung.

## Verlaufsseite (`/verlauf`)

Ein Hintergrund-Thread schreibt alle `VERLAUF_TAKT` Sekunden einen Messpunkt in
`/data/verlauf.sqlite` (im vorhandenen Volume): belegte Slots, verfügbare Slots,
geladene Modelle, VRAM, GPU-Auslastung, abgeschlossene Anfragen, Median-Antwortzeit
und Fehler. Die Seite zeigt daraus vier Kurven für 1 Stunde, 24 Stunden, 7 oder
30 Tage, dazu Kennzahlen und auf Wunsch die Messwerte als Tabelle.

- Zeiträume über einer Stunde werden in der SQL-Abfrage zu Stunden- bzw.
  6-Stunden-Mitteln verdichtet, damit die Diagramme nicht Tausende Punkte zeichnen.
- Anfragen werden ohne Doppelzählung erfasst: Statt Uhren abzugleichen, merkt sich
  die Aufzeichnung den Zeitstempel des jüngsten bereits gezählten Logeintrags.
- Aufgeräumt wird stündlich; Messpunkte älter als `VERLAUF_TAGE` fallen weg.
- Die Diagramme sind selbst gezeichnetes SVG – keine externe Bibliothek, weil das
  Portal ohne Internetzugang läuft.
- Fällt eine Quelle aus (kein Docker-Socket, Ollama nicht erreichbar), wird der
  Messpunkt trotzdem geschrieben; die fehlenden Felder bleiben leer.

Mit `VERLAUF_AKTIV=false` lässt sich die Aufzeichnung ganz abschalten.

## Modellverwaltung

Auf der Einstellungsseite, hinter der Anmeldung. Erspart den Weg über SSH auf
den GPU-Server:

- **Liste** aller installierten Modelle mit Größe, Quantisierung und Stand,
  dazu die Belegung der Platte im Modellverzeichnis (`df` im Container).
- **Nachladen und Aktualisieren** über `ollama pull` mit Fortschrittsbalken.
  Der Vorgang läuft in einem Hintergrund-Thread; die Seite fragt den Stand
  jede Sekunde ab. Es läuft immer nur ein Ladevorgang gleichzeitig – zwei
  würden sich Bandbreite und Platte streitig machen.
- **Löschen.** Modelle, die in der `chatLanguageModels.json` der Nutzer stehen,
  sind als solche markiert und verlangen eine ausdrückliche Bestätigung –
  sonst findet VS Code sie anschließend nicht mehr.

## Plausibilitätsprüfung

Übersicht und Einstellungsseite zeigen Hinweise, wenn Konfiguration und
Wirklichkeit auseinanderlaufen. Geprüft wird:

| Prüfung | warum sie zählt |
|---|---|
| `maxInputTokens` > `OLLAMA_CONTEXT_LENGTH` | VS Code darf mehr senden, als ein Slot fasst – der Anfang der Unterhaltung wird stillschweigend abgeschnitten |
| `maxInputTokens + maxOutputTokens` > Kontext | bei langen Unterhaltungen bleibt kein Platz für die volle Antwort |
| geschätzter VRAM > gemessener GPU-Speicher | nennt die noch mögliche Nutzerzahl bzw. Kontextlänge |
| Modell liegt nur teilweise auf der GPU | der Rest liegt im RAM, Antworten werden um ein Vielfaches langsamer |
| quantisierter KV-Cache ohne `OLLAMA_FLASH_ATTENTION` | ältere Ollama-Stände ignorieren die Quantisierung dann |
| `OLLAMA_CONTEXT_LENGTH` nicht gesetzt | Ollamas eigener Standard ist deutlich kleiner |
| `PUBLIC_OLLAMA_URL` nicht auflösbar | sonst trägt niemand eine funktionierende Adresse ein |

Jeder Hinweis nennt Begründung und Gegenmittel. Warnungen sind rot, bloße
Hinweise gelb; ist alles stimmig, verschwindet der Abschnitt.

## Passwortschutz der Einstellungsseite

Beim ersten Aufruf von `/betrieb` fordert das Portal zum Festlegen eines
Passworts auf (mindestens 8 Zeichen). Gespeichert wird ausschließlich ein
**PBKDF2-HMAC-SHA256-Hash mit 240 000 Iterationen und zufälligem 16-Byte-Salz**
unter `/data/auth.json` (Rechte 0600) – das Passwort selbst liegt nirgends auf
der Platte.

Nach der Anmeldung erhält der Browser ein zufälliges Sitzungs-Token als
`HttpOnly`-Cookie (`SameSite=Strict`), gültig für `SITZUNGSDAUER` Sekunden und
bei Nutzung gleitend verlängert. Die Sitzungen liegen nur im Arbeitsspeicher
und sind nach einem Neustart des Portals ungültig. Fünf Fehlversuche sperren
die betreffende Adresse für 60 Sekunden.

Das Passwort lässt sich auf der Seite ändern; das beendet alle offenen
Sitzungen. Vergessen? Dann `docker compose exec portal rm /data/auth.json`
ausführen und den Container neu starten – der nächste Aufruf startet wieder
mit der Ersteinrichtung.

Damit das Passwort einen Neustart überlebt, braucht das Portal ein Volume:

```yaml
volumes:
  - portal-daten:/data
```

Für automatisierte Deployments lässt sich das Passwort alternativ per
`PORTAL_PASSWORT` fest vorgeben; dann entfällt die Ersteinrichtung und die
Änderungsfunktion im Browser.

> Das Cookie wird **ohne** `Secure`-Flag gesetzt, weil das Portal im internen
> Netz über `http` ausgeliefert wird. Passwort und Cookie gehen damit
> unverschlüsselt über das Netz – für ein internes Werkzeug vertretbar, für
> eine Veröffentlichung nach außen nicht. Dort gehört ein TLS-Reverse-Proxy
> davor.

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
| `GET /api/gpu`           | Gemessene GPU-Werte via `nvidia-smi`. |
| `GET /api/pruefung`      | Hinweise auf unstimmige Einstellungen. |
| `GET /verlauf`           | Verlaufsseite. |
| `GET /api/verlauf`       | Messreihen (`?zeitraum=1h\|24h\|7t\|30t`). |
| `GET /api/aktiv`         | Laufende Anfragen je Modell (Proxy-Modus). |
| `GET /api/modelle/liste` | Installierte Modelle und Plattenbelegung. |
| `GET /api/modelle/fortschritt` | Stand eines laufenden `pull`. |
| `POST /api/modelle/laden` \| `/loeschen` | Modell nachladen bzw. entfernen. |
| `POST /api/docker/aktion` | `{"aktion": "start"\|"stopp"\|"neustart"}` |
| `POST /api/docker/einstellungen` | `{"parallel": 4, "kontext": 50000, "kv": "f16"}` |
| `GET /uebersicht`        | Nur-Lese-Übersicht. |
| `GET /api/nutzung`       | Slot-Auslastung aus den Zugriffslogs. |
| `GET /api/auth/status`   | Ist ein Passwort gesetzt, ist die Sitzung gültig? |
| `POST /api/auth/einrichten` \| `/anmelden` \| `/abmelden` \| `/passwort` | Anmeldung. |

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
  auth.py       Passwort-Hash, Sitzungen, Sperre nach Fehlversuchen
  nutzung.py    Slot-Auslastung aus dem Zugriffslog des Containers
  vram.py       VRAM-Schätzung aus Nutzeranzahl, Kontext und KV-Cache-Typ
  gpu.py        Echte GPU-Werte über nvidia-smi im Ollama-Container
  pruefung.py   Plausibilitätsprüfung von Konfiguration und Messwerten
  modelle.py    Modelle auflisten, nachladen (Strom-Fortschritt), löschen
  verlauf.py    Aufzeichnung der Messwerte in SQLite, Verdichtung, Aufräumen
  proxy.py      Weiterleitung an Ollama; zählt laufende Anfragen je Modell
  config.py     Modelle, Endpunkte, Erzeugung der chatLanguageModels.json
  static/       index.html, uebersicht.html, verlauf.html, betrieb.html,
                style.css und je Seite eine .js-Datei
Dockerfile
docker-compose.yml
```

Das Portal nutzt ausschließlich die Python-Standardbibliothek – der Image-Build
braucht daher keinen Zugriff auf PyPI.
