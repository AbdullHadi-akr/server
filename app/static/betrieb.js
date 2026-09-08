"use strict";

let grenzen = null;

// --- Status ------------------------------------------------------------
const meldung = document.getElementById("status-meldung");

function statusKarte(daten) {
  const karte = document.getElementById("status-karte");
  karte.textContent = "";

  if (!daten.ok) {
    karte.appendChild(el("div", "abzeichen fehler", "nicht erreichbar"));
    karte.appendChild(el("p", "detail", daten.fehler));
    karte.appendChild(el("p", "hinweis",
      "Die Betriebsseite braucht Zugriff auf den Docker-Socket. In der " +
      "docker-compose.yml muss /var/run/docker.sock gemountet und " +
      "OLLAMA_CONTAINER auf den Namen des Ollama-Containers gesetzt sein."));
    return;
  }

  const zustand = daten.laeuft ? "ok" : "fehler";
  const kopf = el("div", "kartenkopf");
  kopf.appendChild(el("span", "abzeichen " + zustand, daten.status));
  kopf.appendChild(el("strong", null, daten.name));
  if (daten.gesundheit) kopf.appendChild(el("span", "abzeichen neutral", daten.gesundheit));
  karte.appendChild(kopf);

  const felder = [
    ["Image", daten.image],
    ["Container-ID", daten.id],
    ["Laufzeit", daten.laufzeit || "–"],
    ["Neustart-Regel", daten.neustartRegel || "–"],
    ["Neustarts", String(daten.neustartZaehler)],
    ["GPU", daten.gpu],
  ];
  if (daten.statistik) {
    felder.push(["CPU", daten.statistik.cpuProzent + " %"]);
    felder.push(["Arbeitsspeicher", daten.statistik.ramGib + " GiB"]);
  }
  if (!daten.laeuft && daten.exitCode !== null && daten.exitCode !== undefined) {
    felder.push(["Exit-Code", String(daten.exitCode)]);
  }
  const dl = el("dl");
  felder.forEach(([k, v]) => {
    dl.appendChild(el("dt", null, k));
    dl.appendChild(el("dd", null, v));
  });
  karte.appendChild(dl);

  const eingestellt = el("div", "unterkarte");
  eingestellt.appendChild(el("h4", null, "Gesetzte Umgebungsvariablen"));
  const tabelle = el("dl", "eng");
  Object.entries(daten.einstellungen).forEach(([name, wert]) => {
    tabelle.appendChild(el("dt", null, name));
    tabelle.appendChild(el("dd", null, wert || "(nicht gesetzt – Ollama-Standard)"));
  });
  eingestellt.appendChild(tabelle);
  karte.appendChild(eingestellt);

  if (daten.compose) {
    karte.appendChild(el("p", "tipp",
      "→ Dieser Container gehört zu einem Docker-Compose-Projekt. Übernommene " +
      "Werte gelten sofort, werden aber beim nächsten 'docker compose up' " +
      "wieder aus der compose-Datei überschrieben – dort ebenfalls eintragen."));
  }
  document.getElementById("fuss-container").textContent = daten.name;

  // Knöpfe an den Zustand anpassen.
  document.getElementById("btn-start").disabled = daten.laeuft;
  document.getElementById("btn-stopp").disabled = !daten.laeuft;
  if (!daten.portalDarfSteuern) {
    ["btn-neustart", "btn-start", "btn-stopp", "btn-uebernehmen"].forEach((id) => {
      document.getElementById(id).disabled = true;
      document.getElementById(id).title = "DOCKER_STEUERUNG ist deaktiviert";
    });
  }
}

async function statusLaden() {
  statusKarte(await holen("/api/docker/status"));
  geladeneLaden();
}

async function geladeneLaden() {
  const ziel = document.getElementById("geladen-liste");
  const daten = await holen("/api/geladen");
  ziel.textContent = "";
  if (!daten.ok) {
    ziel.appendChild(el("p", "detail", "Nicht abrufbar: " + daten.fehler));
    return;
  }
  if (!daten.modelle.length) {
    ziel.appendChild(el("p", "hinweis", "Derzeit ist kein Modell geladen."));
    return;
  }
  const dl = el("dl", "eng");
  daten.modelle.forEach((m) => {
    dl.appendChild(el("dt", null, m.name));
    dl.appendChild(el("dd", null,
      m.vramGib + " GiB im GPU-Speicher" +
      (m.nurGpu ? " (vollständig auf der GPU)" : " von " + m.gesamtGib + " GiB – teilweise im RAM!") +
      (m.kontextJeSlot ? " · Kontext je Slot " + zahl(m.kontextJeSlot) : "")));
  });
  ziel.appendChild(dl);
  ziel.appendChild(el("p", "hinweis", "Summe: " + daten.summeGib + " GiB"));
}

async function aktionAusfuehren(name, beschriftung) {
  if (name !== "start" && !window.confirm(
      beschriftung + ": laufende Anfragen brechen ab. Fortfahren?")) return;
  meldung.textContent = beschriftung + " läuft …";
  const daten = await senden("/api/docker/aktion", { aktion: name });
  meldung.textContent = daten.ok ? beschriftung + " erfolgreich" : "Fehler: " + daten.fehler;
  setTimeout(statusLaden, 1500);
}

// --- VRAM-Rechner ------------------------------------------------------
const rParallel = document.getElementById("r-parallel");
const rKontext = document.getElementById("r-kontext");
const fKv = document.getElementById("f-kv");
const fModelle = document.getElementById("f-modelle");

function balken(anteil, passt) {
  const huelle = el("div", "balken");
  const fuellung = el("div", "fuellung " + (passt ? "ok" : "fehler"));
  fuellung.style.width = Math.min(100, anteil) + "%";
  huelle.appendChild(fuellung);
  return huelle;
}

async function berechnen() {
  document.getElementById("a-parallel").textContent = rParallel.value;
  document.getElementById("a-kontext").textContent = zahl(rKontext.value);

  const abfrage = new URLSearchParams({
    parallel: rParallel.value,
    kontext: rKontext.value,
    kv: fKv.value,
    modelle: fModelle.value,
  });
  const daten = await holen("/api/vram?" + abfrage);
  const ziel = document.getElementById("vram-anzeige");
  ziel.textContent = "";
  if (!daten.ok) {
    ziel.appendChild(el("p", "detail", daten.fehler));
    return;
  }
  grenzen = daten;

  const kopf = el("div", "vram-kopf");
  kopf.appendChild(el("div", "grosszahl" + (daten.passt ? "" : " warn"),
    daten.summeGib + " GiB"));
  kopf.appendChild(el("div", "detail",
    "von " + daten.vramGib + " GiB (" + daten.gpu + ") · " + daten.auslastung + " % belegt · " +
    (daten.passt ? daten.reserveGib + " GiB frei" : "passt nicht in den Speicher!")));
  ziel.appendChild(kopf);
  ziel.appendChild(balken(daten.auslastung, daten.passt));

  if (!daten.passt) {
    ziel.appendChild(el("p", "tipp",
      "→ Zu groß. Möglich wären bei diesem Kontext " + daten.maxParallel +
      " Nutzer, oder bei dieser Nutzerzahl " + zahl(daten.maxKontext) +
      " Token Kontext. Alternativ den KV-Cache auf q8_0 stellen – das halbiert ihn."));
  }

  daten.proModell.forEach((m) => {
    const karte = el("div", "karte flach");
    karte.appendChild(el("h4", null, m.model));
    const dl = el("dl", "eng");
    [
      ["Gewichte", m.gewichteGib + " GiB"],
      ["KV-Cache", m.kvGib + " GiB (" + m.kvProTokenKib + " KiB/Token)"],
      ["Rechenpuffer", m.pufferGib + " GiB"],
      ["Summe", m.gesamtGib + " GiB"],
    ].forEach(([k, v]) => {
      dl.appendChild(el("dt", null, k));
      dl.appendChild(el("dd", null, v));
    });
    karte.appendChild(dl);
    ziel.appendChild(karte);
  });

  ziel.appendChild(el("p", "hinweis",
    "Gesamtkontext über alle Slots: " + zahl(daten.gesamtkontext) + " Token · " +
    "KV-Typ " + daten.kvTyp + " (" + daten.kvHinweis + ")"));
}

// Unstimmige Einstellungen direkt am Rechner anzeigen.
async function hinweiseLaden() {
  const ziel = document.getElementById("hinweise");
  const daten = await holen("/api/pruefung");
  ziel.textContent = "";
  if (!daten.ok || !daten.hinweise.length) return;
  daten.hinweise.forEach((h) => {
    const zeile = el("div", "zeile " + (h.stufe === "warnung" ? "fehler" : "warnung"));
    zeile.appendChild(el("div", "symbol", h.stufe === "warnung" ? "❌" : "⚠️"));
    const inhalt = el("div", "inhalt");
    inhalt.appendChild(el("div", "titel", h.titel));
    inhalt.appendChild(el("div", "detail", h.text));
    if (h.abhilfe) inhalt.appendChild(el("div", "tipp", "→ " + h.abhilfe));
    zeile.appendChild(inhalt);
    ziel.appendChild(zeile);
  });
}

async function uebernehmen() {
  const rueckfrage =
    "Der Ollama-Container wird mit OLLAMA_NUM_PARALLEL=" + rParallel.value +
    ", OLLAMA_CONTEXT_LENGTH=" + rKontext.value + " und OLLAMA_KV_CACHE_TYPE=" +
    fKv.value + " neu erstellt.\n\nLaufende Anfragen brechen ab. Fortfahren?";
  if (!window.confirm(rueckfrage)) return;

  const knopf = document.getElementById("btn-uebernehmen");
  const anzeige = document.getElementById("uebernehmen-meldung");
  const ergebnisfeld = document.getElementById("uebernehmen-ergebnis");
  knopf.disabled = true;
  anzeige.textContent = "Container wird neu erstellt …";
  ergebnisfeld.textContent = "";

  const daten = await senden("/api/docker/einstellungen", {
    parallel: Number(rParallel.value),
    kontext: Number(rKontext.value),
    kv: fKv.value,
  });

  if (daten.ok) {
    anzeige.textContent = "Übernommen";
    const liste = el("ul", "protokoll");
    daten.protokoll.forEach((s) => liste.appendChild(el("li", null, s)));
    liste.appendChild(el("li", null, "Sicherung: " + daten.sicherung));
    ergebnisfeld.appendChild(liste);
    if (daten.compose) {
      ergebnisfeld.appendChild(el("p", "tipp",
        "→ Damit die Werte einen 'docker compose up' überleben, in der " +
        "compose-Datei ebenfalls eintragen: OLLAMA_NUM_PARALLEL=" +
        daten.uebernommen.OLLAMA_NUM_PARALLEL + ", OLLAMA_CONTEXT_LENGTH=" +
        daten.uebernommen.OLLAMA_CONTEXT_LENGTH + ", OLLAMA_KV_CACHE_TYPE=" +
        daten.uebernommen.OLLAMA_KV_CACHE_TYPE));
    }
  } else {
    anzeige.textContent = "Fehlgeschlagen";
    ergebnisfeld.appendChild(el("p", "tipp", daten.fehler));
  }
  knopf.disabled = false;
  setTimeout(statusLaden, 2000);
  setTimeout(hinweiseLaden, 2500);
}

// --- Modellverwaltung --------------------------------------------------
let fortschrittTakt = null;

async function modelleLaden() {
  const ziel = document.getElementById("modell-liste");
  const daten = await holen("/api/modelle/liste");
  ziel.textContent = "";

  if (!daten.ok) {
    ziel.appendChild(el("p", "detail", "Nicht abrufbar: " + daten.fehler));
    return;
  }

  const huelle = el("div", "tabellenhuelle");
  const tabelle = el("table", "modelle");
  const kopf = el("tr");
  ["Modell", "Größe", "Quantisierung", "Stand", ""].forEach((t) => {
    kopf.appendChild(el("th", null, t));
  });
  tabelle.appendChild(kopf);

  daten.modelle.forEach((m) => {
    const zeile = el("tr");
    const namensfeld = el("td", "name");
    namensfeld.appendChild(el("span", null, m.name));
    if (m.inKonfiguration) {
      namensfeld.appendChild(el("span", "abzeichen neutral", "in Konfiguration"));
    }
    zeile.appendChild(namensfeld);
    zeile.appendChild(el("td", null, m.groesseGib + " GiB"));
    zeile.appendChild(el("td", null, m.quantisierung || "–"));
    zeile.appendChild(el("td", null, m.geaendert || "–"));

    const knoepfe = el("td");
    const aktualisieren = el("button", null, "Aktualisieren");
    aktualisieren.addEventListener("click", () => modellLaden(m.name));
    const loeschen = el("button", null, "Löschen");
    loeschen.addEventListener("click", () => modellLoeschen(m));
    knoepfe.appendChild(aktualisieren);
    knoepfe.appendChild(loeschen);
    zeile.appendChild(knoepfe);
    tabelle.appendChild(zeile);
  });
  huelle.appendChild(tabelle);
  ziel.appendChild(huelle);

  const teile = ["Zusammen " + daten.summeGib + " GiB"];
  if (daten.platte && daten.platte.ok) {
    teile.push("Platte: " + daten.platte.belegt + " von " + daten.platte.gesamt +
      " belegt (" + daten.platte.anteil + "), " + daten.platte.frei + " frei");
  }
  ziel.appendChild(el("p", "hinweis", teile.join(" · ")));
}

async function modellLaden(name) {
  const feld = document.getElementById("f-modellname");
  const gewaehlt = (name || feld.value).trim();
  const anzeige = document.getElementById("modell-meldung");
  if (!gewaehlt) {
    anzeige.textContent = "Bitte einen Modellnamen angeben.";
    return;
  }
  anzeige.textContent = "…";
  const daten = await senden("/api/modelle/laden", { name: gewaehlt });
  anzeige.textContent = daten.ok ? "" : daten.fehler;
  if (daten.ok) {
    feld.value = "";
    fortschrittVerfolgen();
  }
}

async function modellLoeschen(modell) {
  const frage = modell.inKonfiguration
    ? modell.name + " steht in der chatLanguageModels.json der Nutzer.\n\n" +
      "Nach dem Löschen findet VS Code das Modell nicht mehr. Wirklich löschen?"
    : modell.name + " endgültig löschen?";
  if (!window.confirm(frage)) return;

  const anzeige = document.getElementById("modell-meldung");
  const daten = await senden("/api/modelle/loeschen",
    { name: modell.name, bestaetigt: true });
  anzeige.textContent = daten.ok ? "Gelöscht: " + daten.geloescht : daten.fehler;
  modelleLaden();
}

function fortschrittVerfolgen() {
  if (fortschrittTakt) return;
  fortschrittTakt = setInterval(async () => {
    const daten = await holen("/api/modelle/fortschritt");
    const ziel = document.getElementById("modell-fortschritt");
    ziel.textContent = "";

    if (!daten.modell) return;
    const karte = el("div", "karte flach");
    karte.appendChild(el("h4", null, daten.modell));
    const teile = [daten.status || "…"];
    if (daten.gesamtGib) {
      teile.push(daten.geladenGib + " von " + daten.gesamtGib + " GiB");
    }
    karte.appendChild(el("p", "detail", teile.join(" · ")));
    if (daten.gesamtGib) karte.appendChild(balken(daten.prozent, false));
    if (daten.fehler) karte.appendChild(el("p", "tipp", daten.fehler));
    ziel.appendChild(karte);

    if (!daten.aktiv) {
      clearInterval(fortschrittTakt);
      fortschrittTakt = null;
      modelleLaden();
      statusLaden();
    }
  }, 1000);
}

document.getElementById("btn-modell-laden")
  .addEventListener("click", () => modellLaden());

// --- Logs --------------------------------------------------------------
async function logsLaden() {
  const bereich = document.getElementById("log-bereich");
  const feld = document.getElementById("logtext");
  bereich.hidden = false;
  feld.textContent = "Lade …";
  const daten = await holen("/api/docker/logs?zeilen=300");
  feld.textContent = daten.ok ? (daten.text || "(keine Ausgabe)") : daten.fehler;
  feld.scrollTop = feld.scrollHeight;
}

document.addEventListener("click", async (ereignis) => {
  const knopf = ereignis.target.closest(".kopieren");
  if (!knopf) return;
  const text = document.getElementById(knopf.dataset.ziel).textContent;
  try {
    await navigator.clipboard.writeText(text);
    knopf.textContent = "Kopiert ✓";
    setTimeout(() => { knopf.textContent = "Kopieren"; }, 1500);
  } catch (fehler) {
    knopf.textContent = "Kopieren nicht möglich";
  }
});

// --- Verdrahtung -------------------------------------------------------
document.getElementById("btn-neustart").addEventListener("click", () => aktionAusfuehren("neustart", "Neustart"));
document.getElementById("btn-start").addEventListener("click", () => aktionAusfuehren("start", "Start"));
document.getElementById("btn-stopp").addEventListener("click", () => aktionAusfuehren("stopp", "Stopp"));
document.getElementById("btn-logs").addEventListener("click", logsLaden);
document.getElementById("btn-aktualisieren").addEventListener("click", statusLaden);
document.getElementById("btn-uebernehmen").addEventListener("click", uebernehmen);
document.getElementById("btn-standard").addEventListener("click", () => {
  if (!grenzen) return;
  rParallel.value = grenzen.standard.parallel;
  rKontext.value = grenzen.standard.kontext;
  fKv.value = "f16";
  berechnen();
});

[rParallel, rKontext, fKv, fModelle].forEach((feld) => {
  feld.addEventListener("input", berechnen);
});

// Startwerte aus der Server-Konfiguration übernehmen.
function starten() {
  if (starten.gelaufen) return;
  starten.gelaufen = true;
  holen("/api/vram").then((daten) => {
    if (daten.ok) {
      rParallel.value = daten.standard.parallel;
      rKontext.value = daten.standard.kontext;
    }
    berechnen();
  });
  statusLaden();
  hinweiseLaden();
  modelleLaden();
  fortschrittVerfolgen();
  setInterval(statusLaden, 30000);
}

holen("/healthz").then((d) => {
  document.getElementById("fuss-version").textContent = d.version || "?";
});

// Die Einstellungen sind Administratoren vorbehalten; normale Nutzer sehen
// nur den Hinweis aus #kein-zugriff.
Anmeldung.start({ nurAdmin: true, beiAnmeldung: starten });
