"use strict";

let daten = null;

async function holen(pfad) {
  const antwort = await fetch(pfad);
  if (!antwort.ok) throw new Error("HTTP " + antwort.status);
  return antwort.json();
}

function el(tag, klasse, text) {
  const knoten = document.createElement(tag);
  if (klasse) knoten.className = klasse;
  if (text !== undefined) knoten.textContent = text;
  return knoten;
}

function zeile({ ok, titel, detail, tipp, ms, laeuft, warnung }) {
  const zustand = laeuft ? "laeuft" : warnung ? "warnung" : ok ? "ok" : "fehler";
  const symbole = { laeuft: "⏳", warnung: "⚠️", ok: "✅", fehler: "❌" };
  const wurzel = el("div", "zeile " + zustand);
  wurzel.appendChild(el("div", "symbol", symbole[zustand]));
  const inhalt = el("div", "inhalt");
  inhalt.appendChild(el("div", "titel", titel));
  if (detail) inhalt.appendChild(el("div", "detail", detail));
  if (!ok && !laeuft && tipp) inhalt.appendChild(el("div", "tipp", "→ " + tipp));
  wurzel.appendChild(inhalt);
  if (ms) wurzel.appendChild(el("div", "dauer", ms >= 1000 ? (ms / 1000).toFixed(1) + " s" : ms + " ms"));
  return wurzel;
}

// --- Seite mit Konfiguration und Modellen füllen -----------------------
async function seiteAufbauen() {
  daten = await holen("/api/modelle");
  const konfig = await holen("/api/vscode-config");

  document.getElementById("kopf-url").textContent = daten.publicUrl;
  document.getElementById("fuss-url").textContent = daten.publicUrl;
  document.getElementById("fuss-version").textContent = daten.version || "?";
  document.getElementById("curl-test").textContent = "curl " + daten.publicUrl + "/api/version";
  // Vier Leerzeichen Einrückung – so, wie die Vorlage vorgegeben ist.
  document.getElementById("konfig").textContent = JSON.stringify(konfig, null, 4);
  document.getElementById("modellnamen").textContent =
    daten.modelle.map((m) => m.name).join(" oder ");

  const karten = document.getElementById("modellkarten");
  karten.textContent = "";
  daten.modelle.forEach((modell) => {
    const karte = el("div", "karte");
    karte.appendChild(el("h3", null, modell.name));
    karte.appendChild(el("p", "hinweis", modell.beschreibung));
    const dl = el("dl");
    const felder = [
      ["Modell-ID", modell.id],
      ["Endpunkt", daten.publicUrl],
      ["Tool Calling", modell.toolCalling ? "ja" : "nein"],
      ["Vision", modell.vision ? "ja" : "nein"],
      ["Kontext", modell.maxInputTokens.toLocaleString("de-DE") + " Token"],
      ["Ausgabe", modell.maxOutputTokens.toLocaleString("de-DE") + " Token"],
    ];
    felder.forEach(([k, v]) => {
      dl.appendChild(el("dt", null, k));
      dl.appendChild(el("dd", null, v));
    });
    karte.appendChild(dl);
    karten.appendChild(karte);
  });
}

// --- Kopieren-Knöpfe ---------------------------------------------------
document.addEventListener("click", async (ereignis) => {
  const knopf = ereignis.target.closest(".kopieren");
  if (!knopf) return;
  const text = document.getElementById(knopf.dataset.ziel).textContent;
  try {
    await navigator.clipboard.writeText(text);
  } catch (fehler) {
    // Fallback, wenn die Zwischenablage-API blockiert ist (z. B. ohne HTTPS).
    const feld = document.createElement("textarea");
    feld.value = text;
    document.body.appendChild(feld);
    feld.select();
    document.execCommand("copy");
    feld.remove();
  }
  const alt = knopf.textContent;
  knopf.textContent = "Kopiert ✓";
  setTimeout(() => { knopf.textContent = alt; }, 1500);
});

// --- Diagnose ----------------------------------------------------------
const status = document.getElementById("status-text");

async function diagnose() {
  const ziel = document.getElementById("diagnose-ergebnis");
  const knopf = document.getElementById("btn-diagnose");
  knopf.disabled = true;
  status.textContent = "Prüfe Ollama …";
  ziel.textContent = "";
  ziel.appendChild(zeile({ laeuft: true, titel: "Prüfung läuft", detail: "Frage " + daten.ollamaUrl + " ab" }));

  try {
    const ergebnis = await holen("/api/diagnose");
    ziel.textContent = "";
    ergebnis.schritte.forEach((s) => {
      ziel.appendChild(zeile({ ok: s.ok, titel: s.titel, detail: s.info || s.beschreibung, tipp: s.hilfe, ms: s.ms }));
    });
    status.textContent = ergebnis.ok
      ? "Alles in Ordnung (" + ergebnis.zeitpunkt + ")"
      : "Es gibt Probleme – Details oben";
  } catch (fehler) {
    ziel.textContent = "";
    ziel.appendChild(zeile({ ok: false, titel: "Portal konnte die Prüfung nicht ausführen", detail: String(fehler) }));
    status.textContent = "Fehler";
  } finally {
    knopf.disabled = false;
  }
}

// --- Live-Test der Modelle --------------------------------------------
async function modelltest() {
  const ziel = document.getElementById("test-ergebnis");
  const knopf = document.getElementById("btn-modelltest");
  knopf.disabled = true;
  ziel.textContent = "";
  status.textContent = "Sende Testanfragen (Kaltstart kann dauern) …";

  for (const modell of daten.modelle) {
    const platzhalter = zeile({
      laeuft: true,
      titel: modell.id,
      detail: "Testanfrage läuft – beim ersten Aufruf lädt Ollama das Modell.",
    });
    ziel.appendChild(platzhalter);
    try {
      const ergebnis = await holen("/api/test?model=" + encodeURIComponent(modell.id));
      const teile = [];
      let warnung = false;
      if (ergebnis.ok) {
        teile.push('Antwort: "' + ergebnis.antwort + '"');
        if (ergebnis.hinweis) { teile.push(ergebnis.hinweis); warnung = true; }
        if (ergebnis.kalt) teile.push("(Kaltstart – Folgeanfragen sind deutlich schneller)");
        if (ergebnis.tools) {
          if (ergebnis.tools.ok) {
            teile.push("Tool Calling: " + ergebnis.tools.info);
          } else {
            // Fehlendes Tool Calling ist kein Ausfall des Endpunkts,
            // sondern nur eine Einschränkung – daher nur eine Warnung.
            teile.push("Tool Calling: " + ergebnis.tools.fehler);
            warnung = true;
          }
        }
      } else {
        teile.push(ergebnis.fehler);
      }
      platzhalter.replaceWith(zeile({
        ok: ergebnis.ok,
        warnung: ergebnis.ok && warnung,
        titel: modell.name + " – " + modell.id,
        detail: teile.join(" · "),
        tipp: "Auf dem Server prüfen mit: ollama run " + modell.id,
        ms: ergebnis.ms,
      }));
    } catch (fehler) {
      platzhalter.replaceWith(zeile({ ok: false, titel: modell.id, detail: String(fehler) }));
    }
  }
  status.textContent = "Modelltest abgeschlossen";
  knopf.disabled = false;
}

document.getElementById("btn-diagnose").addEventListener("click", diagnose);
document.getElementById("btn-modelltest").addEventListener("click", modelltest);

seiteAufbauen()
  .then(diagnose)
  .catch((fehler) => {
    status.textContent = "Portal-Daten konnten nicht geladen werden: " + fehler;
  });
