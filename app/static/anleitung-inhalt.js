"use strict";

// Die Inhalte der Anleitung als Daten, nicht als HTML-Text: Der Aufbereiter in
// anleitung.js macht daraus DOM-Knoten. Alle Zahlen hier stammen aus dem Code
// (app/vram.py, app/reservierung.py, app/proxy.py, app/verlauf.py) - wer dort
// etwas ändert, ändert es bitte auch hier.

const KAPITEL = [
  {
    id: "ueberblick",
    titel: "Überblick",
    kurz: "Was das Portal tut und welchen Weg eine Anfrage nimmt.",
    bloecke: [
      { typ: "text", inhalt:
        "Auf dem GPU-Server läuft Ollama mit zwei Sprachmodellen. Das Portal " +
        "sitzt davor: Es erklärt die Einrichtung in VS Code, zeigt Zustand und " +
        "Auslastung, verwaltet Konten und lässt Rechenzeit reservieren." },
      { typ: "code", titel: "Der Weg einer Anfrage", inhalt:
        "VS Code  ──►  Portal (Port 5021)  ──►  Ollama (Port 5020)  ──►  GPU\n" +
        "                    │\n" +
        "                    └─ erkennt den Nutzer am Zugangsschlüssel,\n" +
        "                       zählt laufende Anfragen je Modell,\n" +
        "                       setzt Reservierungen durch" },
      { typ: "text", inhalt:
        "Weil jede Anfrage durch das Portal läuft, kann es überhaupt erst " +
        "sagen, wer gerade wie viele Slots belegt. Ohne diesen Weg wären nur " +
        "Schätzungen möglich." },
      { typ: "tabelle", kopf: ["Seite", "wofür"], zeilen: [
        ["Einrichtung", "Anleitung für VS Code samt fertigem Konfigurationsblock und Funktionsprüfung"],
        ["Übersicht", "Zustand jetzt: GPU, Modelle, belegte Slots"],
        ["Verlauf", "Entwicklung über Stunden, Tage, Wochen"],
        ["Reservierungen", "Slots für ein Zeitfenster sichern"],
        ["Einstellungen", "Container und Modelle verwalten (Administratoren)"],
        ["Benutzer", "Konten und Rollen (Administratoren)"],
        ["Konto", "Eigener Zugangsschlüssel und Passwort"],
      ] },
      { typ: "hinweis", stufe: "hinweis", inhalt:
        "Einrichtung, Übersicht, Verlauf und diese Anleitung sind ohne " +
        "Anmeldung zugänglich. Alles Weitere setzt ein Konto voraus, das ein " +
        "Administrator anlegt." },
    ],
  },
  {
    id: "einrichtung",
    titel: "Einrichtung in VS Code",
    kurz: "Modelle im Chat verfügbar machen und den Zugangsschlüssel eintragen.",
    bloecke: [
      { typ: "schritte", inhalt: [
        ["Modellverwaltung öffnen",
         "Strg+Shift+P drücken und „Chat: Manage Language Models“ auswählen."],
        ["Eigenen Endpunkt anlegen",
         "„Add Models“ → „Custom Endpoint“. Wo VS Code nach einem API-Key " +
         "fragt, gehört der persönliche Zugangsschlüssel aus der Seite Konto " +
         "hinein – daran erkennt das Portal, wer anfragt."],
        ["Konfiguration einfügen",
         "Weiter, bis sich chatLanguageModels.json öffnet. Das erzeugte " +
         "Template löschen und den Block von der Seite Einrichtung einfügen. " +
         "Dort steht er immer passend zur laufenden Konfiguration – deshalb " +
         "wird er hier nicht wiederholt."],
        ["Modell im Chat wählen",
         "Im Chat-Fenster oben rechts die Modellauswahl öffnen und qwen3 (A100) " +
         "oder qwen3-coder (A100) auswählen."],
      ] },
      { typ: "hinweis", stufe: "hinweis", inhalt:
        "Die erste Antwort kann eine Weile dauern: Ollama lädt das Modell erst " +
        "in den GPU-Speicher. Alle weiteren Antworten kommen zügig. Das ist " +
        "kein Fehler." },
      { typ: "text", inhalt:
        "Welches Modell wofür: qwen3:30b-a3b ist der Allrounder für Chat und " +
        "Fragen zum Code, qwen3-coder:30b ist auf Programmierung und " +
        "Werkzeugaufrufe zugeschnitten." },
    ],
  },
  {
    id: "uebersicht",
    titel: "Übersicht",
    kurz: "GPU, geladene Modelle und belegte Slots – der Zustand von jetzt.",
    bloecke: [
      { typ: "text", inhalt:
        "Die Seite zeigt den Zustand des Dienstes und aktualisiert sich " +
        "selbständig. Sie ist die erste Anlaufstelle bei „warum ist es gerade " +
        "langsam?“." },
      { typ: "liste", titel: "Was dort steht", inhalt: [
        "Dienst – läuft der Container, seit wann, welche GPU ist zugewiesen.",
        "GPU – tatsächlich gemessene Werte über nvidia-smi: belegter und freier " +
        "Speicher, Auslastung, Temperatur. Ist die Messung nicht möglich, sagt " +
        "die Seite das und rechnet mit dem konfigurierten Wert weiter.",
        "Modelle und Slots – welches Modell im Speicher liegt, wie viel VRAM es " +
        "belegt und wie viele Slots es bereitstellt.",
        "Slot-Auslastung – wie viele Anfragen gerade laufen, und der Rückblick " +
        "auf die letzten 15 und 60 Minuten.",
        "Hinweise – erscheinen nur, wenn etwas nicht zusammenpasst.",
      ] },
      { typ: "text", inhalt:
        "Liegt ein Modell nur teilweise auf der GPU, wird das eigens markiert. " +
        "Der Rest liegt dann im Arbeitsspeicher, und die Antworten werden um " +
        "ein Vielfaches langsamer – das ist der häufigste Grund für plötzliche " +
        "Trägheit." },
      { typ: "hinweis", stufe: "warnung", inhalt:
        "Live-Zahl und Rückblick messen Verschiedenes. Live zählt die gerade " +
        "laufenden Anfragen. Der Rückblick stammt aus dem Zugriffslog und kennt " +
        "nur abgeschlossene Anfragen – laufende tauchen dort erst auf, wenn sie " +
        "fertig sind." },
    ],
  },
  {
    id: "verlauf",
    titel: "Verlauf",
    kurz: "Auslastung, Speicher und Anfragen über Stunden bis Wochen.",
    bloecke: [
      { typ: "text", inhalt:
        "Ein Messpunkt je Minute wandert in eine Datei auf dem Server. Die " +
        "Seite zeichnet daraus vier Kurven für 1 Stunde, 24 Stunden, 7 oder " +
        "30 Tage. Sie beantwortet die Frage, die eine Momentaufnahme nicht " +
        "beantworten kann: Reicht die Kapazität?" },
      { typ: "tabelle", kopf: ["Kurve", "beantwortet"], zeilen: [
        ["Belegte Slots", "Wie oft war alles ausgelastet? Die gestrichelte Linie ist die Kapazität."],
        ["GPU-Speicher", "Wie nah kommen wir an die Grenze der Karte?"],
        ["Anfragen", "Wann ist Betrieb – und wann liegt die GPU brach?"],
        ["Antwortzeit", "Werden die Antworten unter Last spürbar langsamer?"],
      ] },
      { typ: "text", inhalt:
        "Zeiträume über einer Stunde werden zusammengefasst, damit die " +
        "Diagramme lesbar bleiben: 7 Tage als Stundenmittel, 30 Tage in " +
        "6-Stunden-Schritten. Die Spitzenwerte bleiben dabei erhalten – eine " +
        "kurze Volllast verschwindet also nicht im Mittelwert." },
      { typ: "hinweis", stufe: "hinweis", inhalt:
        "Über „Tabelle anzeigen“ lassen sich dieselben Werte als Zahlen lesen. " +
        "Aufbewahrt werden sie 30 Tage." },
    ],
  },
  {
    id: "reservierungen",
    titel: "Reservierungen",
    kurz: "Slots für ein Zeitfenster sichern – und was das für andere bedeutet.",
    bloecke: [
      { typ: "text", inhalt:
        "Wer weiß, dass er nachmittags eine größere Aufgabe rechnen lässt, " +
        "sichert sich Kapazität: „3 Slots auf qwen3:30b-a3b von 13 bis 15 Uhr.“ " +
        "Während des Fensters hält das Portal diese Slots frei." },
      { typ: "liste", titel: "Regeln beim Anlegen", inhalt: [
        "Beginn und Ende liegen auf einer Viertelstunde (:00, :15, :30, :45).",
        "Höchstens 4 Stunden am Stück.",
        "Ein Ende vor dem Beginn meint den Folgetag – 23:00 bis 01:00 ist also möglich.",
        "Normale Nutzer müssen einen Slot für alle anderen frei lassen; " +
        "Administratoren dürfen ein Modell ganz belegen.",
        "Überlappende Reservierungen dürfen zusammen die Slot-Zahl nicht überschreiten.",
        "Stornieren darf jeder seine eigene Reservierung, Administratoren alle. " +
        "Die Kapazität ist sofort wieder frei.",
      ] },
      { typ: "text", inhalt:
        "Freigehalten wird hart: Die Slots bleiben über das ganze Fenster " +
        "reserviert, auch wenn gerade nichts gerechnet wird. Das ist für den " +
        "Reservierenden verlässlich und der Grund, warum die Dauer begrenzt ist." },
      { typ: "code", titel: "Wie viel darf ich gerade?", inhalt:
        "frei_für_alle    = Slots − Summe aller Reservierungen\n" +
        "überzug_anderer  = Σ über andere: max(0, laufend − reserviert)\n" +
        "erlaubt_für_mich = eigene Reservierung + max(0, frei_für_alle − überzug_anderer)" },
      { typ: "text", inhalt:
        "Wer reserviert hat, bekommt also seine Slots plus den freien Rest, " +
        "solange ihn niemand sonst braucht. Beispiel mit 4 Slots, 3 davon für " +
        "Meier reserviert: Meier darf 4 gleichzeitig, solange sonst niemand " +
        "rechnet. Sobald jemand anderes den freien Slot nutzt, bleiben Meier " +
        "genau seine 3 – und der andere bekommt keinen zweiten." },
      { typ: "hinweis", stufe: "warnung", inhalt:
        "Wird das Erlaubte überschritten, weist das Portal die Anfrage ab. In " +
        "VS Code erscheint dann eine Meldung, die nennt, wer bis wann " +
        "reserviert hat. Das ist kein Fehler, sondern die Reservierung bei der " +
        "Arbeit." },
    ],
  },
  {
    id: "einstellungen",
    titel: "Einstellungen",
    kurz: "Container steuern, Nutzeranzahl und Kontext festlegen, Modelle pflegen.",
    nurAdmin: true,
    bloecke: [
      { typ: "text", inhalt:
        "Diese Seite verändert den laufenden Betrieb für alle. Sie zeigt den " +
        "Zustand des Ollama-Containers, erlaubt Start, Stopp und Neustart und " +
        "gibt Einblick in die letzten Log-Zeilen." },
      { typ: "liste", titel: "Nutzeranzahl und Kontext", inhalt: [
        "Nutzeranzahl ist OLLAMA_NUM_PARALLEL: so viele Anfragen bearbeitet " +
        "Ollama je Modell gleichzeitig.",
        "Kontext ist OLLAMA_CONTEXT_LENGTH und gilt je Slot, nicht insgesamt.",
        "Der Rechner zeigt sofort, wie viel Speicher die Kombination braucht " +
        "und ob sie in die Karte passt.",
      ] },
      { typ: "hinweis", stufe: "warnung", inhalt:
        "Docker kann die Umgebung eines laufenden Containers nicht ändern. " +
        "Beim Übernehmen wird der Container deshalb gestoppt, als Sicherung " +
        "umbenannt und mit gleicher Konfiguration neu angelegt. Volumes, " +
        "Portbindungen, GPU-Zuweisung und heruntergeladene Modelle bleiben " +
        "erhalten; laufende Anfragen brechen ab. Schlägt der Start fehl, wird " +
        "der alte Container automatisch wiederhergestellt." },
      { typ: "text", inhalt:
        "Gehört der Container zu einem Compose-Projekt, gelten übernommene " +
        "Werte sofort – werden aber vom nächsten „docker compose up“ wieder " +
        "aus der compose-Datei überschrieben. Die Seite weist darauf hin und " +
        "nennt die einzutragenden Werte." },
      { typ: "liste", titel: "Modellverwaltung", inhalt: [
        "Liste der installierten Modelle mit Größe, Quantisierung und Stand.",
        "Nachladen und Aktualisieren mit Fortschrittsanzeige; es läuft immer " +
        "nur ein Ladevorgang.",
        "Löschen – Modelle, die in der Nutzerkonfiguration stehen, sind " +
        "markiert und verlangen eine ausdrückliche Bestätigung.",
      ] },
    ],
  },
  {
    id: "benutzer",
    titel: "Benutzer",
    kurz: "Konten anlegen, Rollen vergeben, Zugangsschlüssel erneuern.",
    nurAdmin: true,
    bloecke: [
      { typ: "tabelle", kopf: ["Rolle", "darf"], zeilen: [
        ["admin", "alles: Container steuern, Einstellungen ändern, Modelle verwalten, Konten anlegen"],
        ["nutzer", "anmelden, reservieren, eigenen Schlüssel und eigenes Passwort verwalten"],
      ] },
      { typ: "text", inhalt:
        "Beim Anlegen erzeugt das Portal einen Zugangsschlüssel und zeigt ihn " +
        "genau einmal an – gespeichert wird nur sein Abdruck. Der Schlüssel " +
        "gehört an die betreffende Person weitergegeben; geht er verloren, " +
        "erzeugt man einen neuen." },
      { typ: "liste", titel: "Eingebaute Sicherungen", inhalt: [
        "Der letzte aktive Administrator lässt sich weder herabstufen noch " +
        "sperren noch löschen.",
        "Niemand löscht sein eigenes Konto.",
        "Änderungen an Rolle, Zustand oder Passwort beenden die offenen " +
        "Sitzungen des Kontos sofort.",
        "Ein gesperrtes Konto verliert auch seinen Zugang für Chat-Anfragen.",
      ] },
    ],
  },
  {
    id: "konto",
    titel: "Konto",
    kurz: "Eigener Zugangsschlüssel und eigenes Passwort.",
    bloecke: [
      { typ: "text", inhalt:
        "Der Zugangsschlüssel weist dich gegenüber dem Portal aus. Er gehört " +
        "in VS Code dorthin, wo nach einem API-Key gefragt wird. Damit werden " +
        "deine Anfragen dir zugeordnet – und nur so greifen deine " +
        "Reservierungen." },
      { typ: "hinweis", stufe: "warnung", inhalt:
        "Gespeichert wird nur der Abdruck des Schlüssels, nicht der Schlüssel " +
        "selbst. Er ist deshalb ausschließlich unmittelbar nach dem Erzeugen " +
        "im Klartext zu sehen. Verloren? Einen neuen erzeugen und in VS Code " +
        "eintragen – der alte wird damit sofort ungültig." },
      { typ: "text", inhalt:
        "Ein Passwortwechsel beendet alle offenen Sitzungen, auch die eigene. " +
        "Danach ist eine neue Anmeldung nötig." },
    ],
  },
  {
    id: "begriffe",
    titel: "Begriffe und Rechenwege",
    kurz: "Slot, Kontext, KV-Cache – und woher die VRAM-Zahlen kommen.",
    bloecke: [
      { typ: "liste", titel: "Begriffe", inhalt: [
        "Slot – ein Platz für eine gleichzeitige Anfrage. Ollama hält je " +
        "geladenem Modell so viele Slots bereit, wie die Nutzeranzahl angibt.",
        "Kontext – wie viele Token eine Unterhaltung umfassen darf. Gilt je " +
        "Slot; jeder Slot hat seinen eigenen Speicher dafür.",
        "KV-Cache – der Zwischenspeicher, in dem das Modell die bisherige " +
        "Unterhaltung hält. Er macht den größten veränderlichen Teil des " +
        "VRAM-Bedarfs aus.",
        "Tool Calling – die Fähigkeit, Werkzeuge aufzurufen, statt nur Text zu " +
        "schreiben. Nötig für den Agentenbetrieb in VS Code.",
      ] },
      { typ: "code", titel: "VRAM-Bedarf", inhalt:
        "VRAM = Gewichte + KV-Cache + Rechenpuffer\n" +
        "KV-Cache = 96 KiB je Token × Nutzeranzahl × Kontext × KV-Faktor" },
      { typ: "text", inhalt:
        "Die 96 KiB folgen aus dem Aufbau von qwen3-30b-a3b: 2 (Schlüssel und " +
        "Wert) × 4 KV-Heads × 128 Head-Dim × 48 Layer × 2 Byte. Die Gewichte " +
        "belegen rund 17,3 GiB. Gegenprobe an gemessenen Werten: 4 Nutzer mit " +
        "je 50 000 Token ergeben 17,3 + 18,3 + 1,4 = 37,0 GiB – gemessen " +
        "wurden 37 GiB." },
      { typ: "tabelle", kopf: ["KV-Cache-Typ", "Speicher", "Qualität"], zeilen: [
        ["f16", "voll", "Standard, höchste Qualität"],
        ["q8_0", "halb", "Verlust kaum messbar"],
        ["q4_0", "ein Viertel", "spürbarer Verlust"],
      ] },
      { typ: "text", inhalt:
        "Slots insgesamt: Die Nutzeranzahl gilt je Modell. Sind zwei Modelle " +
        "geladen und stehen 4 parallele Anfragen ein, gibt es 8 Slots." },
      { typ: "liste", titel: "Wie Auslastung gemessen wird", inhalt: [
        "Live – das Portal kennt jede laufende Anfrage, weil sie durch es " +
        "hindurchgeht, samt Modell und Nutzer.",
        "Rückblick – aus dem Zugriffslog von Ollama: Endzeitpunkt und Dauer " +
        "jeder abgeschlossenen Anfrage ergeben, wie viele gleichzeitig liefen.",
        "VRAM – gemessen über nvidia-smi, daneben der rechnerisch erwartete " +
        "Wert aus der Formel oben.",
      ] },
    ],
  },
  {
    id: "hilfe",
    titel: "Wenn etwas nicht geht",
    kurz: "Häufige Fälle mit Ursache und Gegenmittel.",
    bloecke: [
      { typ: "tabelle", kopf: ["Beobachtung", "Ursache und Abhilfe"], zeilen: [
        ["Die erste Antwort dauert sehr lange",
         "Ollama lädt das Modell in den Speicher. Normal; die folgenden Antworten kommen zügig."],
        ["Antwort wird abgewiesen mit Hinweis auf eine Reservierung",
         "Jemand hat Slots reserviert. Später erneut versuchen oder selbst reservieren."],
        ["Meldung „kein gültiger Zugangsschlüssel“",
         "Der Schlüssel fehlt oder gehört zu einem gesperrten Konto. Unter Konto einen neuen erzeugen und in VS Code eintragen."],
        ["Das Modell erscheint nicht in der Auswahl",
         "JSON-Syntax prüfen (Komma nach jeder Zeile außer der letzten) und VS Code neu laden: Strg+Shift+P → „Developer: Reload Window“."],
        ["Alles ist spürbar langsam",
         "Übersicht ansehen: Liegt ein Modell nur teilweise auf der GPU, oder sind alle Slots belegt?"],
        ["Endpunkt nicht erreichbar",
         "Die Funktionsprüfung auf der Seite Einrichtung nennt die Ursache – Namensauflösung, Port oder Dienst."],
      ] },
      { typ: "hinweis", stufe: "hinweis", inhalt:
        "Die Funktionsprüfung auf der Startseite geht die Kette Schritt für " +
        "Schritt durch und benennt zu jedem Fehler das Gegenmittel. Sie ist " +
        "der schnellste Weg zur Ursache." },
    ],
  },
];
