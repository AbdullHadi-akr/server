"use strict";

function el(tag, klasse, text) {
  const knoten = document.createElement(tag);
  if (klasse) knoten.className = klasse;
  if (text !== undefined) knoten.textContent = text;
  return knoten;
}

function zahl(wert) {
  return Number(wert).toLocaleString("de-DE");
}

async function holen(pfad) {
  const antwort = await fetch(pfad);
  return antwort.json().catch(() => ({ ok: false, fehler: "HTTP " + antwort.status }));
}

function liste(paare) {
  const dl = el("dl", "eng");
  paare.forEach(([k, v]) => {
    dl.appendChild(el("dt", null, k));
    dl.appendChild(el("dd", null, v));
  });
  return dl;
}

function balken(anteil, kritisch) {
  const huelle = el("div", "balken");
  const fuellung = el("div", "fuellung " + (kritisch ? "fehler" : "ok"));
  fuellung.style.width = Math.min(100, Math.max(0, anteil)) + "%";
  huelle.appendChild(fuellung);
  return huelle;
}

// --- Dienst ------------------------------------------------------------
async function dienst() {
  const ziel = document.getElementById("status-karte");
  const daten = await holen("/api/docker/status");
  ziel.textContent = "";
  if (!daten.ok) {
    ziel.appendChild(el("div", "abzeichen fehler", "kein Docker-Zugriff"));
    ziel.appendChild(el("p", "detail", daten.fehler));
    return daten;
  }
  const kopf = el("div", "kartenkopf");
  kopf.appendChild(el("span", "abzeichen " + (daten.laeuft ? "ok" : "fehler"), daten.status));
  kopf.appendChild(el("strong", null, daten.name));
  if (daten.gesundheit) kopf.appendChild(el("span", "abzeichen neutral", daten.gesundheit));
  ziel.appendChild(kopf);

  const felder = [
    ["Image", daten.image],
    ["Laufzeit", daten.laufzeit || "–"],
    ["GPU", daten.gpu],
    ["Slots je Modell", daten.einstellungen.OLLAMA_NUM_PARALLEL || "(Ollama-Standard)"],
    ["Kontext je Slot", daten.einstellungen.OLLAMA_CONTEXT_LENGTH
      ? zahl(daten.einstellungen.OLLAMA_CONTEXT_LENGTH) + " Token" : "(Ollama-Standard)"],
    ["KV-Cache", daten.einstellungen.OLLAMA_KV_CACHE_TYPE || "f16 (Standard)"],
  ];
  if (daten.statistik) {
    felder.push(["CPU", daten.statistik.cpuProzent + " %"]);
    felder.push(["Arbeitsspeicher", daten.statistik.ramGib + " GiB"]);
  }
  ziel.appendChild(liste(felder));
  return daten;
}

// --- GPU ---------------------------------------------------------------
async function grafikkarte() {
  const ziel = document.getElementById("gpu-karte");
  const daten = await holen("/api/gpu");
  ziel.textContent = "";

  if (!daten.gemessen) {
    ziel.appendChild(el("p", "detail",
      "Keine Messwerte: " + (daten.fehler || "unbekannter Grund")));
    ziel.appendChild(el("p", "hinweis",
      (daten.hilfe || "") + " Gerechnet wird mit " + daten.vramGib + " GiB."));
    return daten;
  }

  daten.gpus.forEach((g) => {
    const karte = el("div", "karte");
    const kopf = el("div", "kartenkopf");
    kopf.appendChild(el("span", "abzeichen ok", "gemessen"));
    kopf.appendChild(el("strong", null, g.name));
    karte.appendChild(kopf);
    karte.appendChild(liste([
      ["VRAM", g.vramBelegtGib + " von " + g.vramGesamtGib + " GiB belegt"],
      ["Frei", g.vramFreiGib + " GiB"],
      ["Auslastung", g.auslastung === null ? "–" : g.auslastung + " %"],
      ["Temperatur", g.temperatur === null ? "–" : g.temperatur + " °C"],
      ["Leistung", g.leistungWatt === null ? "–" : g.leistungWatt + " W"],
    ]));
    const anteil = g.vramGesamtGib ? (g.vramBelegtGib / g.vramGesamtGib) * 100 : 0;
    karte.appendChild(balken(anteil, anteil > 95));
    ziel.appendChild(karte);
  });
  return daten;
}

// --- Hinweise ----------------------------------------------------------
async function hinweise() {
  const bereich = document.getElementById("hinweise-bereich");
  const ziel = document.getElementById("hinweise");
  const daten = await holen("/api/pruefung");
  ziel.textContent = "";

  if (!daten.ok || !daten.hinweise.length) {
    bereich.hidden = true;
    return;
  }
  bereich.hidden = false;
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

// --- GPU-Speicher ------------------------------------------------------
async function speicher(status) {
  const ziel = document.getElementById("vram-karte");
  const geladen = await holen("/api/geladen");
  ziel.textContent = "";

  const parallel = Number((status.einstellungen || {}).OLLAMA_NUM_PARALLEL) || 4;
  const kontext = Number((status.einstellungen || {}).OLLAMA_CONTEXT_LENGTH) || 50000;
  const kv = (status.einstellungen || {}).OLLAMA_KV_CACHE_TYPE || "f16";
  const anzahl = Math.max(1, (geladen.modelle || []).length);
  const schaetzung = await holen(
    "/api/vram?parallel=" + parallel + "&kontext=" + kontext +
    "&kv=" + encodeURIComponent(kv) + "&modelle=" + Math.min(anzahl, 2));

  const belegt = geladen.ok ? geladen.summeGib : 0;
  const gesamt = schaetzung.ok ? schaetzung.vramGib : 0;
  const anteil = gesamt ? (belegt / gesamt) * 100 : 0;

  const kopf = el("div", "vram-kopf");
  kopf.appendChild(el("div", "grosszahl", belegt.toFixed(2) + " GiB"));
  kopf.appendChild(el("div", "detail",
    geladen.ok
      ? "von Ollama belegt, von " + gesamt + " GiB" +
        (schaetzung.ok ? " · rechnerisch erwartet: " + schaetzung.summeGib + " GiB" : "")
      : "Belegung nicht abrufbar: " + geladen.fehler));
  ziel.appendChild(kopf);
  ziel.appendChild(balken(anteil, anteil > 95));

  if (geladen.ok && !geladen.modelle.length) {
    ziel.appendChild(el("p", "hinweis",
      "Zurzeit ist kein Modell geladen – der Speicher ist frei. Beim nächsten " +
      "Chat lädt Ollama das Modell nach, die erste Antwort dauert dann länger."));
  }
  return { geladen, schaetzung, parallel, kontext };
}

// --- Modelle und Slots -------------------------------------------------
function modelle(daten, auslastung) {
  const ziel = document.getElementById("modell-karten");
  ziel.textContent = "";
  const { geladen, schaetzung, parallel, kontext } = daten;

  if (!geladen.ok) {
    ziel.appendChild(el("p", "detail", "Nicht abrufbar: " + geladen.fehler));
    return;
  }
  if (!geladen.modelle.length) {
    ziel.appendChild(el("p", "hinweis", "Derzeit ist kein Modell im Speicher."));
    return;
  }

  const nutzungsdaten = auslastung;
  const spitze = nutzungsdaten && nutzungsdaten.fenster && nutzungsdaten.fenster.length
    ? nutzungsdaten.fenster[0].spitze : null;
  const live = nutzungsdaten && nutzungsdaten.live && nutzungsdaten.live.ok
    ? nutzungsdaten.live : null;

  geladen.modelle.forEach((m) => {
    const karte = el("div", "karte");
    const kopf = el("div", "kartenkopf");
    kopf.appendChild(el("span", "abzeichen ok", "geladen"));
    kopf.appendChild(el("strong", null, m.name));
    if (!m.nurGpu) kopf.appendChild(el("span", "abzeichen fehler", "teilweise im RAM"));
    karte.appendChild(kopf);

    // Ollama meldet in /api/ps die Kontextlaenge je Slot - also den Wert aus
    // OLLAMA_CONTEXT_LENGTH. Der Gesamtkontext ist das Vielfache davon.
    const kontextJeSlot = m.kontextJeSlot || kontext;
    karte.appendChild(liste([
      ["Belegter VRAM", m.vramGib + " GiB"],
      ["Slots", parallel + " × " + zahl(kontextJeSlot) + " Token"],
      ["Gesamtkontext", zahl(parallel * kontextJeSlot) + " Token"],
      ["Bereitgehalten bis", m.laeuftBis ? new Date(m.laeuftBis).toLocaleString("de-DE") : "–"],
    ]));

    // Im Proxy-Modus ist die Belegung je Modell bekannt, sonst nur insgesamt.
    const jeModell = (live && live.jeModell || []).find((e) => e.modell === m.name);
    if (jeModell) {
      karte.appendChild(el("p", "hinweis",
        "Jetzt aktiv: " + jeModell.rechnend + " von " + jeModell.slots + " Slots" +
        (jeModell.wartend ? " · " + jeModell.wartend + " Anfrage(n) in der Warteschlange" : "")));
      karte.appendChild(slotReihe(jeModell.aktiv, jeModell.slots));
    } else if (live && live.quelle === "proxy") {
      karte.appendChild(el("p", "hinweis",
        "Zurzeit keine laufende Anfrage für dieses Modell."));
    } else if (live) {
      karte.appendChild(el("p", "hinweis",
        "Dieses Modell stellt " + parallel + " der insgesamt " + live.slots +
        " Slots. Ohne Proxy-Modus lässt sich die Belegung nicht je Modell " +
        "trennen – siehe Slot-Auslastung unten."));
    }
    ziel.appendChild(karte);
  });

  if (geladen.modelle.length > 1 && schaetzung.ok && !schaetzung.passt) {
    ziel.appendChild(el("p", "tipp",
      "→ Beide Modelle gleichzeitig geladen überschreiten rechnerisch den " +
      "verfügbaren Speicher. Wenn ein Modell teilweise im RAM liegt, wird es " +
      "deutlich langsamer."));
  }
}

// --- Auslastung --------------------------------------------------------
function slotReihe(aktiv, slots) {
  const reihe = el("div", "slots");
  const felder = Math.max(slots, aktiv);
  for (let i = 0; i < felder; i += 1) {
    const belegt = i < aktiv;
    const ueberzaehlig = i >= slots;
    reihe.appendChild(el(
      "div",
      "slot" + (belegt ? (ueberzaehlig ? " ueberzaehlig" : " belegt") : ""),
      belegt ? (ueberzaehlig ? "wartet" : "aktiv") : "frei"));
  }
  return reihe;
}

function liveKarte(live, slots) {
  const ziel = document.getElementById("live-karte");
  ziel.textContent = "";

  if (!live) {
    ziel.appendChild(el("p", "detail", "Keine Live-Messung verfügbar."));
    return;
  }
  if (!live.ok) {
    ziel.appendChild(el("p", "detail", "Live-Messung nicht möglich: " + live.fehler));
    ziel.appendChild(el("p", "hinweis",
      "Dafür liest das Portal /proc/net/tcp im Ollama-Container. Das braucht " +
      "Zugriff auf den Docker-Socket und einen Container, in dem 'cat' " +
      "vorhanden ist. Der Rückblick unten funktioniert unabhängig davon."));
    return;
  }

  const karte = el("div", "karte");
  const kopf = el("div", "vram-kopf");
  kopf.appendChild(el("div", "grosszahl" + (live.ueberbucht ? " warn" : ""),
    live.aktiv + " von " + live.slots));
  kopf.appendChild(el("div", "detail",
    live.ueberbucht
      ? "mehr offene Sitzungen als Slots – Anfragen warten in der Warteschlange"
      : "aktive Sitzungen · " + live.frei + " Slots frei"));
  karte.appendChild(kopf);
  karte.appendChild(slotReihe(live.aktiv, live.slots));

  // OLLAMA_NUM_PARALLEL gilt je Modell – die Gesamtzahl der Slots ergibt
  // sich erst mit der Anzahl geladener Modelle.
  if (live.slotsJeModell) {
    karte.appendChild(el("p", "hinweis",
      live.slotsJeModell + " Slots je Modell × " +
      (live.modelleGeladen || 0) + " geladene Modelle = " + live.slots +
      " Slots insgesamt" +
      (live.modelleGeladen ? "" :
        " (kein Modell geladen – gerechnet wird mit einem)")));
  }
  if (live.jeBenutzer && live.jeBenutzer.length) {
    const zeile = el("p", "hinweis", "Gerade aktiv: " + live.jeBenutzer
      .map((b) => b.name + " (" + b.aktiv + ")").join(" · "));
    karte.appendChild(zeile);
  }
  karte.appendChild(el("p", "hinweis", live.quelle === "proxy"
    ? "Exakt gezählt: Die Anfragen laufen durch den Portal-Proxy auf Port " +
      live.port + ", der jede laufende Anfrage samt Modell kennt."
    : "Gezählt werden die gerade offenen Verbindungen zu Ollama (Port " +
      live.port + "). VS Code hält je laufendem Chat eine Verbindung; nach der " +
      "Antwort kann sie noch kurz bestehen bleiben. Die " + live.eigene +
      " Abfrage(n) dieser Seite sind herausgerechnet. Die Verbindung verrät " +
      "nicht, welches Modell sie nutzt – die Zahl gilt daher für alle " +
      "geladenen Modelle zusammen."));
  ziel.appendChild(karte);
}

async function auslastung() {
  const ziel = document.getElementById("nutzung-karte");
  const hinweisfeld = document.getElementById("nutzung-hinweis");
  const anzeige = document.getElementById("nutzung-status");
  anzeige.textContent = "lädt …";
  const daten = await holen("/api/nutzung");
  ziel.textContent = "";
  hinweisfeld.textContent = "";
  anzeige.textContent = "Stand " + new Date().toLocaleTimeString("de-DE");

  if (!daten.ok) {
    liveKarte(null);
    ziel.appendChild(el("p", "detail", "Nicht abrufbar: " + daten.fehler));
    return null;
  }
  liveKarte(daten.live, daten.slots);
  if (!daten.fenster.length) {
    ziel.appendChild(el("p", "hinweis", daten.hinweis));
    return daten;
  }

  daten.fenster.forEach((f) => {
    const karte = el("div", "karte flach");
    karte.appendChild(el("h4", null, "Letzte " + f.minuten + " Minuten"));
    karte.appendChild(liste([
      ["Anfragen", zahl(f.anfragen)],
      ["Höchste Gleichzeitigkeit", f.spitze + " von " + daten.slots + " Slots (" + f.auslastung + " %)"],
      ["Mittlere Belegung", f.mittel + " Slots"],
      ["Antwortzeit (Median)", f.medianSekunden + " s"],
      ["Längste Anfrage", (f.laengsteSekunden || 0) + " s"],
      ["Fehlerhafte Anfragen", zahl(f.fehler)],
    ]));
    karte.appendChild(balken(f.auslastung, f.auslastung >= 100));
    ziel.appendChild(karte);
  });

  hinweisfeld.textContent =
    "Rückblick aus " + zahl(daten.erkannt) + " Zugriffen im Log des Containers, " +
    "letzter Eintrag " + daten.letzteAnfrage + ". Eine Anfrage erscheint erst im " +
    "Log, wenn sie beantwortet ist – laufende Sitzungen stehen deshalb nur in " +
    "der Live-Anzeige oben. Der Rückblick gilt – wie die Live-Anzeige – für " +
    "alle geladenen Modelle zusammen, da das Zugriffslog das Modell nicht " +
    "mitschreibt; verglichen wird daher mit allen " + daten.slots + " Slots.";
  return daten;
}

// --- Ablauf ------------------------------------------------------------
let letzteSpeicherdaten = null;

async function aktualisieren() {
  const status = await dienst();
  if (!status.ok) return;
  const [speicherDaten, nutzungDaten] = await Promise.all([
    speicher(status), auslastung(), grafikkarte(), hinweise(),
  ]);
  letzteSpeicherdaten = speicherDaten;
  modelle(speicherDaten, nutzungDaten);
  document.getElementById("fuss-zeit").textContent =
    "Stand " + new Date().toLocaleTimeString("de-DE");
}

// Die Auslastung laesst sich unabhaengig vom Rest neu laden.
async function nurAuslastung() {
  const knopf = document.getElementById("btn-nutzung");
  knopf.disabled = true;
  try {
    const daten = await auslastung();
    if (letzteSpeicherdaten) modelle(letzteSpeicherdaten, daten);
  } finally {
    knopf.disabled = false;
  }
}

let takt = null;
function taktSetzen() {
  if (takt) clearInterval(takt);
  takt = document.getElementById("f-auto").checked
    ? setInterval(nurAuslastung, 10000)
    : null;
}

document.getElementById("btn-nutzung").addEventListener("click", nurAuslastung);
document.getElementById("f-auto").addEventListener("change", taktSetzen);

holen("/healthz").then((d) => {
  document.getElementById("fuss-version").textContent = d.version || "?";
});
aktualisieren();
taktSetzen();
setInterval(aktualisieren, 30000);
