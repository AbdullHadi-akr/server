"use strict";

const NS = "http://www.w3.org/2000/svg";
let zeitraum = "24h";
let daten = null;
let tabelleSichtbar = false;

function el(tag, klasse, text) {
  const knoten = document.createElement(tag);
  if (klasse) knoten.className = klasse;
  if (text !== undefined) knoten.textContent = text;
  return knoten;
}

function svgEl(tag, attribute) {
  const knoten = document.createElementNS(NS, tag);
  Object.entries(attribute || {}).forEach(([k, v]) => knoten.setAttribute(k, v));
  return knoten;
}

function zahl(wert, stellen) {
  return Number(wert).toLocaleString("de-DE", {
    minimumFractionDigits: stellen || 0, maximumFractionDigits: stellen || 0,
  });
}

function uhrzeit(sekunden, lang) {
  const d = new Date(sekunden * 1000);
  return lang
    ? d.toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
    : d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

async function holen(pfad) {
  const antwort = await fetch(pfad);
  return antwort.json().catch(() => ({ ok: false, fehler: "HTTP " + antwort.status }));
}

// --- Diagramm ----------------------------------------------------------
// Eine Datenreihe je Diagramm: keine Legende nötig, der Titel benennt sie.
// Beschriftet wird nur der letzte Punkt, nicht jeder.
function zeichnen(behaelter, einstellung) {
  const punkte = einstellung.punkte;
  behaelter.textContent = "";

  if (!punkte.length) {
    behaelter.appendChild(el("div", "leer",
      "Noch keine Messwerte für diesen Zeitraum."));
    return;
  }

  const breite = Math.max(320, behaelter.clientWidth - 28);
  const hoehe = 200;
  const links = 52, rechts = 58, oben = 14, unten = 26;
  const flaecheB = breite - links - rechts;
  const flaecheH = hoehe - oben - unten;

  const werte = punkte.map(einstellung.wert);
  const bezug = einstellung.referenz ? Math.max(...punkte.map(einstellung.referenz)) : 0;
  const rohMax = Math.max(...werte, bezug, einstellung.mindestMax || 0);
  const max = rohMax <= 0 ? 1 : rohMax * 1.12;
  const t0 = punkte[0].zeit;
  const t1 = punkte[punkte.length - 1].zeit;
  const spanne = Math.max(1, t1 - t0);

  const x = (t) => links + ((t - t0) / spanne) * flaecheB;
  const y = (w) => oben + flaecheH - (w / max) * flaecheH;

  const svg = svgEl("svg", { viewBox: `0 0 ${breite} ${hoehe}`, height: hoehe,
                             role: "img", "aria-label": einstellung.beschreibung });

  // Gitter: hauchdünn und zurückhaltend, gerundete Achsenwerte.
  const stufen = 4;
  for (let i = 0; i <= stufen; i += 1) {
    const wert = (max / stufen) * i;
    const hoeheY = y(wert);
    svg.appendChild(svgEl("line", { class: "gitterlinie", x1: links, x2: breite - rechts,
                                    y1: hoeheY, y2: hoeheY }));
    const beschriftung = svgEl("text", { class: "achse", x: links - 8, y: hoeheY + 4,
                                         "text-anchor": "end" });
    beschriftung.textContent = zahl(wert, einstellung.stellen);
    svg.appendChild(beschriftung);
  }

  // Kapazitätslinie (z. B. verfügbare Slots oder GPU-Speicher)
  if (bezug > 0) {
    svg.appendChild(svgEl("line", { class: "referenz", x1: links, x2: breite - rechts,
                                    y1: y(bezug), y2: y(bezug) }));
    const marke = svgEl("text", { class: "achse", x: breite - rechts + 6, y: y(bezug) + 4 });
    marke.textContent = einstellung.referenzText || "";
    svg.appendChild(marke);
  }

  if (einstellung.art === "saeulen") {
    // Säulen: höchstens 24 px breit, 2 px Luft zwischen den Marken.
    const breiteJe = Math.min(24, Math.max(2, (flaecheB / punkte.length) - 2));
    punkte.forEach((p, i) => {
      const wert = werte[i];
      if (!wert) return;
      const hoeheS = Math.max(2, oben + flaecheH - y(wert));
      svg.appendChild(svgEl("rect", {
        x: x(p.zeit) - breiteJe / 2, y: y(wert), width: breiteJe, height: hoeheS,
        rx: Math.min(4, breiteJe / 2), fill: "var(--serie)",
      }));
    });
  } else {
    const pfad = punkte.map((p, i) => `${i ? "L" : "M"}${x(p.zeit).toFixed(1)},${y(werte[i]).toFixed(1)}`).join(" ");
    if (einstellung.art === "flaeche") {
      svg.appendChild(svgEl("path", {
        d: `${pfad} L${x(t1).toFixed(1)},${oben + flaecheH} L${x(t0).toFixed(1)},${oben + flaecheH} Z`,
        fill: "var(--serie-wash)", stroke: "none",
      }));
    }
    svg.appendChild(svgEl("path", { d: pfad, fill: "none", stroke: "var(--serie)",
                                    "stroke-width": 2, "stroke-linejoin": "round",
                                    "stroke-linecap": "round" }));
    // Endpunkt mit Ring in Flächenfarbe, damit er sich abhebt.
    svg.appendChild(svgEl("circle", { cx: x(t1), cy: y(werte[werte.length - 1]), r: 4,
                                      fill: "var(--serie)", stroke: "var(--flaeche)",
                                      "stroke-width": 2 }));
  }

  // Nur der letzte Wert wird direkt beschriftet.
  const letzter = svgEl("text", { class: "wertlabel", x: breite - rechts + 6,
                                  y: y(werte[werte.length - 1]) + 4 });
  letzter.textContent = zahl(werte[werte.length - 1], einstellung.stellen) +
    (einstellung.einheit ? " " + einstellung.einheit : "");
  svg.appendChild(letzter);

  // Zeitachse: wenige Marken statt einer je Punkt.
  const marken = Math.min(5, punkte.length);
  for (let i = 0; i < marken; i += 1) {
    const p = punkte[Math.round((punkte.length - 1) * (i / Math.max(1, marken - 1)))];
    const text = svgEl("text", { class: "achse", x: x(p.zeit), y: hoehe - 8,
                                 "text-anchor": i === 0 ? "start" : (i === marken - 1 ? "end" : "middle") });
    text.textContent = zeitraum === "1h" || zeitraum === "24h"
      ? uhrzeit(p.zeit) : uhrzeit(p.zeit, true);
    svg.appendChild(text);
  }

  // Fadenkreuz und Sprechblase beim Überfahren.
  const linie = svgEl("line", { class: "gitterlinie", y1: oben, y2: oben + flaecheH,
                                stroke: "var(--gedaempft)", opacity: 0 });
  svg.appendChild(linie);
  const blase = el("div", "spitzenmarke");
  behaelter.appendChild(blase);

  const feld = svgEl("rect", { x: links, y: oben, width: flaecheB, height: flaecheH,
                               fill: "transparent" });
  svg.appendChild(feld);

  function zeigen(ereignis) {
    const kasten = svg.getBoundingClientRect();
    const relativ = (ereignis.clientX - kasten.left) / kasten.width * breite;
    let naechster = punkte[0], abstand = Infinity;
    punkte.forEach((p) => {
      const d = Math.abs(x(p.zeit) - relativ);
      if (d < abstand) { abstand = d; naechster = p; }
    });
    linie.setAttribute("x1", x(naechster.zeit));
    linie.setAttribute("x2", x(naechster.zeit));
    linie.setAttribute("opacity", 0.5);
    blase.textContent = "";
    blase.appendChild(el("div", "zeit", uhrzeit(naechster.zeit, true)));
    blase.appendChild(el("div", "wert", einstellung.blase(naechster)));
    blase.style.opacity = 1;
    const links_px = (x(naechster.zeit) / breite) * kasten.width;
    blase.style.left = Math.min(kasten.width - 140, Math.max(0, links_px - 60)) + "px";
    blase.style.top = "8px";
  }

  feld.addEventListener("mousemove", zeigen);
  feld.addEventListener("mouseleave", () => {
    blase.style.opacity = 0;
    linie.setAttribute("opacity", 0);
  });
  behaelter.insertBefore(svg, blase);
}

// --- Seite -------------------------------------------------------------
function kachel(beschriftung, wert, zusatz) {
  const k = el("div", "kachel");
  k.appendChild(el("div", "beschriftung", beschriftung));
  k.appendChild(el("div", "zahl", wert));
  if (zusatz) k.appendChild(el("div", "zusatz", zusatz));
  return k;
}

function kennzahlen(z) {
  const ziel = document.getElementById("kennzahlen");
  ziel.textContent = "";
  if (!z || !z.punkte) return;
  ziel.appendChild(kachel("Anfragen", zahl(z.anfragen),
    z.fehler ? zahl(z.fehler) + " davon fehlerhaft" : "keine Fehler"));
  ziel.appendChild(kachel("Spitze Slots", z.spitzeSlots + " von " + z.slots,
    z.slots ? Math.round(z.spitzeSlots / z.slots * 100) + " % der Kapazität" : ""));
  ziel.appendChild(kachel("VRAM-Spitze", zahl(z.vramSpitze, 1) + " GiB",
    z.vramGesamt ? "von " + zahl(z.vramGesamt, 1) + " GiB" : ""));
  ziel.appendChild(kachel("Antwortzeit", zahl(z.medianS, 1) + " s",
    "Median, nur Zeiten mit Last"));
}

function tabelle() {
  const t = document.getElementById("verlauf-tabelle");
  t.textContent = "";
  const kopf = document.createElement("tr");
  ["Zeit", "Slots belegt", "von", "VRAM GiB", "GPU %", "Anfragen", "Median s"]
    .forEach((titel) => {
      const th = document.createElement("th");
      th.textContent = titel;
      kopf.appendChild(th);
    });
  t.appendChild(kopf);
  daten.punkte.slice().reverse().forEach((p) => {
    const zeile = document.createElement("tr");
    [uhrzeit(p.zeit, true), p.spitze, p.slots, zahl(p.vramBelegt, 1),
     zahl(p.gpuLast, 0), p.anfragen, zahl(p.medianS, 1)].forEach((wert) => {
      const td = document.createElement("td");
      td.textContent = wert;
      zeile.appendChild(td);
    });
    t.appendChild(zeile);
  });
}

function alleZeichnen() {
  const p = daten.punkte;
  document.getElementById("slots-erklaerung").textContent =
    "Die gestrichelte Linie ist die verfügbare Kapazität: " +
    "OLLAMA_NUM_PARALLEL mal Anzahl geladener Modelle.";

  zeichnen(document.getElementById("d-slots"), {
    punkte: p, wert: (d) => d.spitze, referenz: (d) => d.slots,
    referenzText: "Kapazität", art: "flaeche", einheit: "", stellen: 0,
    beschreibung: "Belegte Slots über die Zeit",
    blase: (d) => d.spitze + " von " + d.slots + " Slots belegt",
  });
  zeichnen(document.getElementById("d-vram"), {
    punkte: p, wert: (d) => d.vramBelegt, referenz: (d) => d.vramGesamt,
    referenzText: "GPU", art: "flaeche", einheit: "GiB", stellen: 1,
    beschreibung: "Belegter GPU-Speicher über die Zeit",
    blase: (d) => zahl(d.vramBelegt, 1) + " von " + zahl(d.vramGesamt, 1) + " GiB",
  });
  zeichnen(document.getElementById("d-anfragen"), {
    punkte: p, wert: (d) => d.anfragen, art: "saeulen", stellen: 0, mindestMax: 4,
    beschreibung: "Abgeschlossene Anfragen je Messpunkt",
    blase: (d) => d.anfragen + " Anfragen" + (d.fehler ? ", " + d.fehler + " fehlerhaft" : ""),
  });
  zeichnen(document.getElementById("d-antwort"), {
    punkte: p, wert: (d) => d.medianS, art: "linie", einheit: "s", stellen: 1,
    beschreibung: "Median der Antwortzeit über die Zeit",
    blase: (d) => zahl(d.medianS, 1) + " s Median bei " + d.anfragen + " Anfragen",
  });
}

async function laden() {
  const anzeige = document.getElementById("verlauf-status");
  anzeige.textContent = "lädt …";
  daten = await holen("/api/verlauf?zeitraum=" + zeitraum);
  if (!daten.ok) {
    anzeige.textContent = "Nicht abrufbar: " + (daten.fehler || "unbekannt");
    return;
  }
  anzeige.textContent = daten.punkte.length
    ? daten.punkte.length + " Messpunkte"
    : "Noch keine Daten. Die Aufzeichnung beginnt mit dem Start des Portals.";
  kennzahlen(daten.zusammenfassung);
  alleZeichnen();
  if (tabelleSichtbar) tabelle();
  document.getElementById("fuss-info").textContent =
    "Messpunkt alle " + daten.takt + " s · Aufbewahrung " +
    daten.aufbewahrungTage + " Tage" +
    (daten.verdichtung ? " · verdichtet auf " + (daten.verdichtung / 3600) + "-Stunden-Mittel" : "");
}

document.querySelectorAll(".zeitraum").forEach((knopf) => {
  knopf.addEventListener("click", () => {
    document.querySelectorAll(".zeitraum").forEach((k) => k.classList.remove("aktiv"));
    knopf.classList.add("aktiv");
    zeitraum = knopf.dataset.zeitraum;
    laden();
  });
});

document.getElementById("btn-tabelle").addEventListener("click", (e) => {
  tabelleSichtbar = !tabelleSichtbar;
  document.getElementById("tabellen-bereich").hidden = !tabelleSichtbar;
  e.target.textContent = tabelleSichtbar ? "Tabelle ausblenden" : "Tabelle anzeigen";
  if (tabelleSichtbar && daten) tabelle();
});

// Bei Größenänderung neu zeichnen: die Diagramme werden in Pixeln gerechnet,
// damit Schrift und Linien nicht verzerren.
let umbauTakt = null;
window.addEventListener("resize", () => {
  clearTimeout(umbauTakt);
  umbauTakt = setTimeout(() => { if (daten && daten.ok) alleZeichnen(); }, 200);
});

versionAnzeigen();
navigationLaden();
laden();
setInterval(laden, 60000);
