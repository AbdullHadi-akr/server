"use strict";

let zustand = null;

function weiterZiel() {
  // Wer von einer geschützten Seite kam, soll dorthin zurück.
  const ziel = new URLSearchParams(window.location.search).get("weiter");
  // Nur seiteneigene Pfade zulassen - kein Sprung auf fremde Adressen.
  return ziel && ziel.startsWith("/") && !ziel.startsWith("//")
    ? ziel : "/uebersicht";
}

async function aufbauen() {
  zustand = await holen("/api/auth/status");
  navigationAufbauen(zustand);

  if (zustand.angemeldet) {
    window.location.href = weiterZiel();
    return;
  }

  const erst = !zustand.eingerichtet;
  document.getElementById("titel").textContent =
    erst ? "Administrator anlegen" : "Anmelden";
  document.getElementById("btn-anmelden").textContent =
    erst ? "Konto anlegen" : "Anmelden";
  document.getElementById("wiederholung-block").hidden = !erst;
  document.getElementById("f-passwort").autocomplete =
    erst ? "new-password" : "current-password";

  let text;
  if (erst) {
    text = "Es gibt noch kein Konto. Lege jetzt den Administrator an " +
      "(Passwort mindestens " + zustand.minLaenge + " Zeichen). Gespeichert " +
      "wird nur ein Hash, nie das Passwort selbst.";
    if (!zustand.speicherbar) {
      text += " Achtung: " + zustand.datenVerzeichnis + " ist nicht " +
        "beschreibbar. Ohne eingebundenes Volume lässt sich kein Konto " +
        "speichern.";
    }
  } else {
    text = "Einrichtung, Übersicht und Verlauf sind ohne Anmeldung zugänglich. " +
      "Für Reservierungen und Einstellungen bitte anmelden. Konten legt ein " +
      "Administrator an.";
  }
  document.getElementById("anmeldung-text").textContent = text;
}

document.getElementById("anmelde-formular").addEventListener("submit", async (e) => {
  e.preventDefault();
  const anzeige = document.getElementById("anmelde-meldung");
  const passwort = document.getElementById("f-passwort");
  const erst = zustand && !zustand.eingerichtet;

  if (erst && passwort.value !== document.getElementById("f-passwort2").value) {
    anzeige.textContent = "Die beiden Eingaben stimmen nicht überein.";
    return;
  }
  anzeige.textContent = "…";
  const daten = await senden(erst ? "/api/auth/einrichten" : "/api/auth/anmelden", {
    name: document.getElementById("f-name").value,
    passwort: passwort.value,
  });
  if (!daten.ok) {
    anzeige.textContent = daten.fehler;
    return;
  }
  passwort.value = "";
  anzeige.textContent = "";

  if (daten.token) {
    // Bei der Ersteinrichtung ist der Zugangsschlüssel nur jetzt zu sehen.
    const ziel = document.getElementById("token-anzeige");
    ziel.textContent = "";
    const karte = el("div", "karte");
    karte.appendChild(el("h4", null, "Zugangsschlüssel für VS Code"));
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
    karte.appendChild(feld);
    karte.appendChild(el("p", "tipp",
      "→ Jetzt notieren: Der Schlüssel ist nur hier und nur jetzt im Klartext " +
      "zu sehen. Weiter geht es über die Navigation."));
    ziel.appendChild(karte);
    navigationAufbauen(await holen("/api/auth/status"));
    return;
  }
  window.location.href = weiterZiel();
});

versionAnzeigen();
aufbauen();
