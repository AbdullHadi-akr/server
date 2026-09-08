"use strict";

const NS = "http://www.w3.org/2000/svg";
let daten = null;
let tag = new Date().toISOString().slice(0, 10);

function svgEl(tagName, attribute) {
  const knoten = document.createElementNS(NS, tagName);
  Object.entries(attribute || {}).forEach(([k, v]) => knoten.setAttribute(k, v));
  return knoten;
}

function uhr(zeitstempel) {
  return new Date(zeitstempel * 1000).toLocaleTimeString("de-DE",
    { hour: "2-digit", minute: "2-digit" });
}

// Reserviert wird im Viertelstundenraster - deshalb Auswahllisten statt
// freier Zeitfelder. "24:00" beim Ende meint Mitternacht des Folgetages.
const RASTER = 15;

function zeitListen() {
  const von = document.getElementById("f-von");
  const bis = document.getElementById("f-bis");
  if (von.options.length) return;

  for (let minute = 0; minute < 24 * 60; minute += RASTER) {
    von.appendChild(zeitOption(minute));
  }
  for (let minute = RASTER; minute <= 24 * 60; minute += RASTER) {
    bis.appendChild(zeitOption(minute));
  }

  // Sinnvolle Vorbelegung: nächste volle Viertelstunde, eine Stunde lang.
  const jetzt = new Date();
  const start = (Math.floor((jetzt.getHours() * 60 + jetzt.getMinutes()) / RASTER)
                 + 1) * RASTER;
  von.value = String(Math.min(start, 23 * 60 + 45));
  bis.value = String(Math.min(start + 60, 24 * 60));
}

function zeitOption(minute) {
  const stunde = Math.floor(minute / 60);
  const rest = minute % 60;
  const eintrag = el("option", null,
    String(stunde).padStart(2, "0") + ":" + String(rest).padStart(2, "0"));
  eintrag.value = String(minute);
  return eintrag;
}

function datumZeit(zeitstempel) {
  return new Date(zeitstempel * 1000).toLocaleString("de-DE",
    { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

// --- Zeitleiste je Modell ----------------------------------------------
// Ein Tag von 0 bis 24 Uhr; jede Reservierung ein Balken, eigene hervorgehoben.
function zeitleiste(modell, eintraege, behaelter) {
  const block = el("div", "zeitleiste");
  block.appendChild(el("h4", null, modell.name + "  ·  " + modell.id));

  const breite = Math.max(320, behaelter.clientWidth - 8);
  const zeilenHoehe = 26;
  const oben = 18;
  const spuren = Math.max(1, eintraege.length);
  const hoehe = oben + spuren * zeilenHoehe + 6;
  const svg = svgEl("svg", { viewBox: `0 0 ${breite} ${hoehe}`, height: hoehe,
                             role: "img",
                             "aria-label": "Belegung von " + modell.id });

  const x = (zeit) => ((zeit - daten.beginn) / 86400) * breite;

  for (let stunde = 0; stunde <= 24; stunde += 3) {
    const px = (stunde / 24) * breite;
    svg.appendChild(svgEl("line", { class: "raster", x1: px, x2: px,
                                    y1: oben - 6, y2: hoehe }));
    const text = svgEl("text", { class: "stunde", x: px + 3, y: 11 });
    text.textContent = stunde + ":00";
    svg.appendChild(text);
  }

  eintraege.forEach((r, i) => {
    const links = Math.max(0, x(r.start));
    const rechts = Math.min(breite, x(r.ende));
    const y = oben + i * zeilenHoehe;
    const eigen = r.benutzer === daten.eigenerName;
    svg.appendChild(svgEl("rect", {
      class: "block" + (eigen ? " eigen" : ""),
      x: links, y: y, width: Math.max(3, rechts - links), height: zeilenHoehe - 6,
    }));
    const beschriftung = svgEl("text", { class: "blocktext", x: links + 6,
                                         y: y + zeilenHoehe - 12 });
    beschriftung.textContent = r.benutzer + " · " + r.slots + " Slots · " +
      uhr(r.start) + "–" + uhr(r.ende) + (r.notiz ? " · " + r.notiz : "");
    svg.appendChild(beschriftung);
  });

  // Markierung für "jetzt", solange der gezeigte Tag der heutige ist.
  const jetzt = Date.now() / 1000;
  if (jetzt > daten.beginn && jetzt < daten.ende) {
    svg.appendChild(svgEl("line", { class: "jetzt", x1: x(jetzt), x2: x(jetzt),
                                    y1: oben - 8, y2: hoehe }));
  }

  if (!eintraege.length) {
    block.appendChild(el("p", "hinweis", "Nichts reserviert."));
  }
  block.appendChild(svg);
  return block;
}

function belegungZeichnen() {
  const ziel = document.getElementById("belegung");
  ziel.textContent = "";
  daten.modelle.forEach((m) => {
    const eintraege = daten.reservierungen.filter((r) => r.modell === m.id);
    ziel.appendChild(zeitleiste(m, eintraege, ziel));
  });
  document.getElementById("tag-status").textContent =
    daten.reservierungen.length + " Reservierungen · " + daten.slots +
    " Slots je Modell";
}

function eigeneZeichnen() {
  const ziel = document.getElementById("eigene-liste");
  ziel.textContent = "";
  if (!daten.eigene.length) {
    ziel.appendChild(el("p", "hinweis", "Keine laufenden oder kommenden Reservierungen."));
    return;
  }
  const huelle = el("div", "tabellenhuelle");
  const tabelle = el("table", "modelle");
  const kopf = el("tr");
  ["Modell", "Von", "Bis", "Slots", "Notiz", ""].forEach(
    (t) => kopf.appendChild(el("th", null, t)));
  tabelle.appendChild(kopf);
  daten.eigene.forEach((r) => {
    const zeile = el("tr");
    // Ausschliesslich im Browser formatieren - sonst zeigt die Tabelle eine
    // andere Uhrzeit als die Zeitleiste darueber.
    [r.modell, datumZeit(r.start), datumZeit(r.ende), r.slots, r.notiz].forEach(
      (w) => zeile.appendChild(el("td", null, String(w))));
    const knopf = el("button", null, "Stornieren");
    knopf.addEventListener("click", async () => {
      if (!window.confirm("Reservierung wirklich stornieren?")) return;
      const antwort = await senden("/api/reservierungen/loeschen", { id: r.id });
      if (!antwort.ok) window.alert(antwort.fehler);
      laden();
    });
    const feld = el("td");
    feld.appendChild(knopf);
    zeile.appendChild(feld);
    tabelle.appendChild(zeile);
  });
  huelle.appendChild(tabelle);
  ziel.appendChild(huelle);
}

async function laden() {
  daten = await holen("/api/reservierungen?tag=" + tag);
  if (!daten.ok) {
    document.getElementById("belegung").textContent = daten.fehler || "Fehler";
    return;
  }
  document.getElementById("f-tag").value = daten.tag;
  belegungZeichnen();

  if (!daten.angemeldet) return;

  const auswahl = document.getElementById("f-modell");
  if (!auswahl.options.length) {
    daten.modelle.forEach((m) => {
      const eintrag = el("option", null, m.name + " (" + m.id + ")");
      eintrag.value = m.id;
      auswahl.appendChild(eintrag);
    });
    document.getElementById("f-datum").value = daten.tag;
  }
  zeitListen();
  const grenze = daten.istAdmin ? daten.slots : daten.slots - daten.minFrei;
  document.getElementById("f-slots").max = grenze;
  document.getElementById("regeln").textContent =
    "Höchstens " + grenze + " von " + daten.slots + " Slots und " +
    daten.maxStunden + " Stunden am Stück." +
    (daten.istAdmin ? " Als Administrator darfst du alle Slots reservieren."
                    : " " + daten.minFrei + " Slot bleibt für alle anderen frei.");
  eigeneZeichnen();
}

function tagWechseln(versatz) {
  const d = new Date(tag + "T12:00");
  d.setDate(d.getDate() + versatz);
  tag = d.toISOString().slice(0, 10);
  laden();
}

document.getElementById("btn-zurueck").addEventListener("click", () => tagWechseln(-1));
document.getElementById("btn-vor").addEventListener("click", () => tagWechseln(1));
document.getElementById("btn-heute").addEventListener("click", () => {
  tag = new Date().toISOString().slice(0, 10);
  laden();
});
document.getElementById("f-tag").addEventListener("change", (e) => {
  tag = e.target.value;
  laden();
});

document.getElementById("reservieren-formular").addEventListener("submit", async (e) => {
  e.preventDefault();
  const anzeige = document.getElementById("reservieren-meldung");
  const datum = document.getElementById("f-datum").value;
  anzeige.textContent = "…";
  // Den Zeitstempel im Browser ausrechnen: Er kennt die Zeitzone des Nutzers.
  // Eine reine Wanduhrzeit wuerde der Server in seiner eigenen Zone deuten.
  const tagesBeginn = new Date(datum + "T00:00").getTime() / 1000;
  const vonMinute = Number(document.getElementById("f-von").value);
  let bisMinute = Number(document.getElementById("f-bis").value);
  // Ein Ende vor dem Beginn meint den Folgetag (etwa 23:00 bis 01:00).
  if (bisMinute <= vonMinute) bisMinute += 24 * 60;

  const antwort = await senden("/api/reservierungen/anlegen", {
    modell: document.getElementById("f-modell").value,
    start: Math.floor(tagesBeginn + vonMinute * 60),
    ende: Math.floor(tagesBeginn + bisMinute * 60),
    slots: Number(document.getElementById("f-slots").value),
    notiz: document.getElementById("f-notiz").value,
  });
  if (!antwort.ok) {
    anzeige.textContent = antwort.fehler;
    return;
  }
  anzeige.textContent = "Reserviert.";
  document.getElementById("f-notiz").value = "";
  tag = datum;
  laden();
});

versionAnzeigen();
seiteAbsichern({ beiZugang: laden });

window.addEventListener("resize", () => { if (daten && daten.ok) belegungZeichnen(); });
