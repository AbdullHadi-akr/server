"use strict";

// Bausteine, die alle Seiten brauchen: kleine DOM-Helfer, HTTP-Aufrufe, die
// rollenabhaengige Navigation und der Zugangsschutz. Wird vor der jeweiligen
// Seiten-Datei eingebunden.

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

async function senden(pfad, rumpf) {
  const antwort = await fetch(pfad, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rumpf || {}),
  });
  const daten = await antwort.json().catch(
    () => ({ ok: false, fehler: "HTTP " + antwort.status }));
  if (antwort.status === 401 && !pfad.startsWith("/api/auth/")) {
    // Sitzung abgelaufen - zur Anmeldeseite und danach hierher zurück.
    const ziel = window.location.pathname + window.location.search;
    window.location.href = "/anmelden?weiter=" + encodeURIComponent(ziel);
  }
  return daten;
}

function liste(paare) {
  const dl = el("dl", "eng");
  paare.forEach(([k, v]) => {
    dl.appendChild(el("dt", null, k));
    dl.appendChild(el("dd", null, v));
  });
  return dl;
}

// --- Navigation --------------------------------------------------------
// Eine einzige Quelle für alle Seiten: Welche Reiter erscheinen, hängt davon
// ab, ob jemand angemeldet ist und welche Rolle er hat.
const REITER_IMMER = [
  ["/", "Einrichtung"],
  ["/uebersicht", "Übersicht"],
  ["/verlauf", "Verlauf"],
];
const REITER_ADMIN = [
  ["/betrieb", "Einstellungen"],
  ["/benutzer", "Benutzer"],
];

function navigationAufbauen(zustand) {
  const navi = document.getElementById("navi");
  if (!navi) return;
  navi.textContent = "";

  // Reihenfolge: erst was alle betrifft, dann die Adminwerkzeuge, Konto zuletzt.
  let reiter = REITER_IMMER.slice();
  if (zustand && zustand.angemeldet) {
    reiter.push(["/reservierungen", "Reservierungen"]);
    if (zustand.istAdmin) reiter = reiter.concat(REITER_ADMIN);
    reiter.push(["/konto", "Konto"]);
  } else {
    reiter.push(["/anmelden", "Anmelden"]);
  }

  const hier = window.location.pathname.replace(/\/$/, "") || "/";
  reiter.forEach(([pfad, beschriftung]) => {
    const verweis = el("a", pfad === hier ? "aktiv" : null, beschriftung);
    verweis.href = pfad;
    navi.appendChild(verweis);
  });

  if (zustand && zustand.angemeldet && zustand.benutzer) {
    const konto = el("span", "navi-konto");
    konto.appendChild(el("span", "navi-name",
      zustand.benutzer.name + " · " + zustand.benutzer.rolle));
    const abmelden = el("button", "navi-abmelden", "Abmelden");
    abmelden.addEventListener("click", async () => {
      await senden("/api/auth/abmelden", {});
      window.location.href = "/uebersicht";
    });
    konto.appendChild(abmelden);
    navi.appendChild(konto);
  }
}

// --- Zugang zu geschützten Seiten --------------------------------------
// Nicht angemeldet? Zur Anmeldeseite und danach zurück. Wer angemeldet ist,
// aber die Rolle nicht hat, bekommt einen Hinweis statt eines leeren Gerüsts.
async function seiteAbsichern(optionen) {
  const zustand = await holen("/api/auth/status");
  navigationAufbauen(zustand);

  if (!zustand.angemeldet) {
    const ziel = window.location.pathname + window.location.search;
    window.location.href = "/anmelden?weiter=" + encodeURIComponent(ziel);
    return null;
  }
  if (optionen && optionen.nurAdmin && !zustand.istAdmin) {
    keinZugriff();
    return null;
  }
  if (optionen && optionen.beiZugang) optionen.beiZugang(zustand);
  return zustand;
}

function keinZugriff() {
  const bereich = document.querySelector("main");
  bereich.textContent = "";
  const abschnitt = el("section");
  abschnitt.appendChild(el("h2", null, "Administratoren vorbehalten"));
  const text = el("p", "hinweis");
  text.appendChild(document.createTextNode("Diese Seite dürfen nur "
    + "Administratoren öffnen. Dein Zugangsschlüssel und deine Reservierungen "
    + "stehen unter "));
  const konto = el("a", null, "Konto");
  konto.href = "/konto";
  text.appendChild(konto);
  text.appendChild(document.createTextNode(", der Zustand des Dienstes unter "));
  const uebersicht = el("a", null, "Übersicht");
  uebersicht.href = "/uebersicht";
  text.appendChild(uebersicht);
  text.appendChild(document.createTextNode("."));
  abschnitt.appendChild(text);
  bereich.appendChild(abschnitt);
}

// Offene Seiten bauen nur die Navigation auf.
function navigationLaden() {
  holen("/api/auth/status").then(navigationAufbauen);
}

// Version im Seitenfuß, sofern die Seite ein Feld dafür hat.
function versionAnzeigen() {
  const feld = document.getElementById("fuss-version");
  if (!feld) return;
  holen("/healthz").then((d) => { feld.textContent = d.version || "?"; });
}
