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
      ? "tatsächlich belegt von " + gesamt + " GiB" +
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

  const spitze = auslastung && auslastung.fenster && auslastung.fenster.length
    ? auslastung.fenster[0].spitze : null;

  geladen.modelle.forEach((m) => {
    const karte = el("div", "karte");
    const kopf = el("div", "kartenkopf");
    kopf.appendChild(el("span", "abzeichen ok", "geladen"));
    kopf.appendChild(el("strong", null, m.name));
    if (!m.nurGpu) kopf.appendChild(el("span", "abzeichen fehler", "teilweise im RAM"));
    karte.appendChild(kopf);

    const kontextJeSlot = m.kontext ? Math.round(m.kontext / parallel) : kontext;
    karte.appendChild(liste([
      ["Belegter VRAM", m.vramGib + " GiB"],
      ["Slots", parallel + " × " + zahl(kontextJeSlot) + " Token"],
      ["Gesamtkontext", zahl(m.kontext || parallel * kontext) + " Token"],
      ["Bereitgehalten bis", m.laeuftBis ? new Date(m.laeuftBis).toLocaleString("de-DE") : "–"],
    ]));

    if (spitze !== null) {
      const anteil = parallel ? (spitze / parallel) * 100 : 0;
      karte.appendChild(el("p", "hinweis",
        "Höchste gleichzeitige Belegung der letzten " +
        auslastung.fenster[0].minuten + " Minuten: " + spitze + " von " +
        parallel + " Slots"));
      karte.appendChild(balken(anteil, anteil >= 100));
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
async function auslastung() {
  const ziel = document.getElementById("nutzung-karte");
  const hinweisfeld = document.getElementById("nutzung-hinweis");
  const daten = await holen("/api/nutzung");
  ziel.textContent = "";
  hinweisfeld.textContent = "";

  if (!daten.ok) {
    ziel.appendChild(el("p", "detail", "Nicht abrufbar: " + daten.fehler));
    return null;
  }
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
    "Ermittelt aus " + zahl(daten.erkannt) + " Zugriffen im Log des Containers, " +
    "letzter Eintrag " + daten.letzteAnfrage + ". Eine Anfrage erscheint erst im " +
    "Log, wenn sie beantwortet ist – gerade laufende Anfragen fehlen daher. " +
    "Die Zahlen gelten für den Ollama-Dienst insgesamt, da das Zugriffslog das " +
    "Modell nicht mitschreibt.";
  return daten;
}

// --- Ablauf ------------------------------------------------------------
async function aktualisieren() {
  const status = await dienst();
  if (!status.ok) return;
  const [speicherDaten, nutzungDaten] = await Promise.all([speicher(status), auslastung()]);
  modelle(speicherDaten, nutzungDaten);
  document.getElementById("fuss-zeit").textContent =
    "Stand " + new Date().toLocaleTimeString("de-DE");
}

holen("/healthz").then((d) => {
  document.getElementById("fuss-version").textContent = d.version || "?";
});
aktualisieren();
setInterval(aktualisieren, 20000);
