"use strict";

let alleZeigen = false;
let gewaehlt = null;

// --- Bausteine der Kapitel ---------------------------------------------
// Jeder Block wird zu DOM-Knoten; Texte gehen über textContent hinein.
const AUFBEREITER = {
  text: (block) => el("p", null, block.inhalt),

  liste: (block) => {
    const huelle = el("div");
    if (block.titel) huelle.appendChild(el("h3", "untertitel", block.titel));
    const ul = el("ul", "aufzaehlung");
    block.inhalt.forEach((eintrag) => ul.appendChild(el("li", null, eintrag)));
    huelle.appendChild(ul);
    return huelle;
  },

  schritte: (block) => {
    const ol = el("ol", "schritte");
    block.inhalt.forEach(([titel, text]) => {
      const li = el("li");
      li.appendChild(el("h3", null, titel));
      li.appendChild(el("p", null, text));
      ol.appendChild(li);
    });
    return ol;
  },

  code: (block) => {
    const huelle = el("div");
    if (block.titel) huelle.appendChild(el("h3", "untertitel", block.titel));
    const kasten = el("div", "codebox");
    kasten.appendChild(el("pre", "formel", block.inhalt));
    huelle.appendChild(kasten);
    return huelle;
  },

  tabelle: (block) => {
    const huelle = el("div", "tabellenhuelle");
    const tabelle = el("table", "modelle");
    const kopf = el("tr");
    block.kopf.forEach((titel) => kopf.appendChild(el("th", null, titel)));
    tabelle.appendChild(kopf);
    block.zeilen.forEach((werte) => {
      const zeile = el("tr");
      werte.forEach((wert) => zeile.appendChild(el("td", null, wert)));
      tabelle.appendChild(zeile);
    });
    huelle.appendChild(tabelle);
    return huelle;
  },

  hinweis: (block) => {
    const zeile = el("div", "zeile " + (block.stufe === "warnung" ? "warnung" : "ok"));
    zeile.appendChild(el("div", "symbol", block.stufe === "warnung" ? "⚠️" : "ℹ️"));
    const inhalt = el("div", "inhalt");
    inhalt.appendChild(el("div", "detail", block.inhalt));
    zeile.appendChild(inhalt);
    return zeile;
  },
};

function kapitelKnoten(kapitel) {
  const abschnitt = el("div", "kapitel");
  const ueberschrift = el("h2");
  ueberschrift.appendChild(el("span", null, kapitel.titel));
  if (kapitel.nurAdmin) {
    ueberschrift.appendChild(el("span", "abzeichen neutral", "nur Administratoren"));
  }
  abschnitt.appendChild(ueberschrift);
  kapitel.bloecke.forEach((block) => {
    const bauer = AUFBEREITER[block.typ];
    if (bauer) abschnitt.appendChild(bauer(block));
  });
  return abschnitt;
}

// --- Kacheln -----------------------------------------------------------
function kachelnZeichnen(suchtext) {
  const ziel = document.getElementById("kachel-bereich");
  ziel.textContent = "";
  const gefiltert = KAPITEL.filter((k) => passt(k, suchtext));

  gefiltert.forEach((kapitel) => {
    const kachel = el("button", "kachel waehlbar" +
      (kapitel.id === gewaehlt && !alleZeigen ? " aktiv" : ""));
    kachel.type = "button";
    const titel = el("div", "kacheltitel", kapitel.titel);
    if (kapitel.nurAdmin) {
      titel.appendChild(el("span", "abzeichen neutral", "Admin"));
    }
    kachel.appendChild(titel);
    kachel.appendChild(el("div", "kachelkurz", kapitel.kurz));
    kachel.addEventListener("click", () => waehlen(kapitel.id));
    ziel.appendChild(kachel);
  });

  const status = document.getElementById("such-status");
  status.textContent = suchtext
    ? gefiltert.length + " von " + KAPITEL.length + " Bereichen"
    : "";
  return gefiltert;
}

function passt(kapitel, suchtext) {
  if (!suchtext) return true;
  const begriff = suchtext.toLowerCase();
  if ((kapitel.titel + " " + kapitel.kurz).toLowerCase().includes(begriff)) return true;
  // Auch im Fließtext suchen, damit „VRAM“ die Kapitel findet, die es erklären.
  return JSON.stringify(kapitel.bloecke).toLowerCase().includes(begriff);
}

// --- Auswahl -----------------------------------------------------------
function waehlen(id, ohneAdresse) {
  alleZeigen = false;
  gewaehlt = id;
  const ziel = document.getElementById("kapitel");
  ziel.textContent = "";
  const kapitel = KAPITEL.find((k) => k.id === id);
  if (kapitel) ziel.appendChild(kapitelKnoten(kapitel));
  kachelnZeichnen(document.getElementById("f-suche").value.trim());
  document.getElementById("btn-alles").textContent = "Alles anzeigen";
  if (!ohneAdresse) {
    // Adresse mitführen, damit sich einzelne Kapitel verlinken lassen.
    history.replaceState(null, "", "#" + id);
  }
  ziel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function alleKapitel() {
  alleZeigen = !alleZeigen;
  const ziel = document.getElementById("kapitel");
  ziel.textContent = "";
  document.getElementById("btn-alles").textContent =
    alleZeigen ? "Einzeln anzeigen" : "Alles anzeigen";

  if (!alleZeigen) {
    waehlen(gewaehlt || KAPITEL[0].id);
    return;
  }
  const suchtext = document.getElementById("f-suche").value.trim();
  KAPITEL.filter((k) => passt(k, suchtext)).forEach(
    (k) => ziel.appendChild(kapitelKnoten(k)));
  kachelnZeichnen(suchtext);
}

document.getElementById("f-suche").addEventListener("input", (e) => {
  const suchtext = e.target.value.trim();
  const gefiltert = kachelnZeichnen(suchtext);
  if (alleZeigen) {
    const ziel = document.getElementById("kapitel");
    ziel.textContent = "";
    gefiltert.forEach((k) => ziel.appendChild(kapitelKnoten(k)));
  } else if (gefiltert.length && !gefiltert.some((k) => k.id === gewaehlt)) {
    // Passt das offene Kapitel nicht mehr zur Suche, das erste Treffer öffnen.
    waehlen(gefiltert[0].id);
  }
});

document.getElementById("btn-alles").addEventListener("click", alleKapitel);

window.addEventListener("hashchange", () => {
  const id = window.location.hash.slice(1);
  if (KAPITEL.some((k) => k.id === id)) waehlen(id, true);
});

versionAnzeigen();
navigationLaden();

// Ein Kapitel aus der Adresse öffnen (z. B. /anleitung#reservierungen),
// sonst mit dem Überblick beginnen.
const gewuenscht = window.location.hash.slice(1);
waehlen(KAPITEL.some((k) => k.id === gewuenscht) ? gewuenscht : KAPITEL[0].id, true);
