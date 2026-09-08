"use strict";

async function kontoLaden() {
  const ziel = document.getElementById("konto-karte");
  const daten = await holen("/api/konto");
  ziel.textContent = "";
  if (!daten.ok) {
    ziel.appendChild(el("p", "detail", daten.fehler));
    return;
  }
  const b = daten.benutzer;
  const karte = el("div", "karte");
  const kopf = el("div", "kartenkopf");
  kopf.appendChild(el("span", "abzeichen " + (b.aktiv ? "ok" : "fehler"),
    b.aktiv ? "aktiv" : "gesperrt"));
  kopf.appendChild(el("strong", null, b.name));
  kopf.appendChild(el("span", "abzeichen neutral", b.rolle));
  karte.appendChild(kopf);
  karte.appendChild(liste([
    ["Angelegt", b.erstellt],
    ["Letzte Anmeldung", b.letzterLogin || "–"],
    ["Schlüssel hinterlegt", b.hatToken ? "ja" : "nein"],
  ]));
  ziel.appendChild(karte);
}

document.getElementById("btn-token").addEventListener("click", async () => {
  if (!window.confirm("Dein bisheriger Schlüssel wird sofort ungültig und muss " +
      "in VS Code ersetzt werden. Fortfahren?")) return;
  const anzeige = document.getElementById("token-meldung");
  anzeige.textContent = "…";
  const daten = await senden("/api/konto/token", {});
  if (!daten.ok) {
    anzeige.textContent = daten.fehler;
    return;
  }
  anzeige.textContent = "";
  const ziel = document.getElementById("token-anzeige");
  ziel.textContent = "";
  const feld = el("div", "codebox");
  const knopf = el("button", "kopieren", "Kopieren");
  knopf.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(daten.token);
      knopf.textContent = "Kopiert ✓";
    } catch (fehler) {
      knopf.textContent = "Kopieren nicht möglich";
    }
  });
  feld.appendChild(knopf);
  feld.appendChild(el("pre", null, daten.token));
  ziel.appendChild(feld);
  ziel.appendChild(el("p", "tipp",
    "→ In VS Code eintragen: Strg+Shift+P → „Chat: Manage Language Models“ → " +
    "beim Anbieter A100 den Schlüssel hinterlegen."));
  kontoLaden();
});

document.getElementById("passwort-formular").addEventListener("submit", async (e) => {
  e.preventDefault();
  const anzeige = document.getElementById("passwort-meldung");
  anzeige.textContent = "…";
  const daten = await senden("/api/auth/passwort", {
    alt: document.getElementById("f-alt").value,
    neu: document.getElementById("f-neu").value,
  });
  if (!daten.ok) {
    anzeige.textContent = daten.fehler;
    return;
  }
  anzeige.textContent = "Geändert – bitte neu anmelden.";
  document.getElementById("f-alt").value = "";
  document.getElementById("f-neu").value = "";
  // Der Wechsel beendet die Sitzung; die Anmeldeseite fängt das ab.
  setTimeout(() => { window.location.href = "/anmelden?weiter=/konto"; }, 1200);
});

versionAnzeigen();
seiteAbsichern({ beiZugang: kontoLaden });
