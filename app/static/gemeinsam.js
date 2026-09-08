"use strict";

// Bausteine, die mehrere Seiten brauchen: kleine DOM-Helfer, HTTP-Aufrufe
// und die Anmeldung. Wird vor der jeweiligen Seiten-Datei eingebunden.

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
    // Sitzung abgelaufen - zurück zur Anmeldung.
    if (window.Anmeldung) window.Anmeldung.zeigen();
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

// --- Anmeldung ---------------------------------------------------------
// Erwartet im HTML die Abschnitte #anmeldung (Formular) und #geschuetzt
// (Inhalt). Ruft nach erfolgreicher Anmeldung den übergebenen Rückruf auf.
window.Anmeldung = (function () {
  let zustand = null;
  let beiAnmeldung = null;
  let nurAdmin = false;

  function zeigen() {
    document.getElementById("anmeldung").hidden = false;
    document.getElementById("geschuetzt").hidden = true;
    const erst = zustand && !zustand.eingerichtet;
    document.getElementById("anmeldung-titel").textContent =
      erst ? "Administrator anlegen" : "Anmeldung";
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
          "beschreibbar – ohne eingebundenes Volume lässt sich kein Konto " +
          "speichern.";
      }
    } else {
      text = "Bitte mit dem persönlichen Konto anmelden. " +
        "Übersicht und Verlauf sind auch ohne Anmeldung zugänglich.";
    }
    document.getElementById("anmeldung-text").textContent = text;
  }

  function inhaltZeigen() {
    document.getElementById("anmeldung").hidden = true;
    document.getElementById("geschuetzt").hidden = false;
    if (beiAnmeldung) beiAnmeldung(zustand);
  }

  async function pruefen() {
    zustand = await holen("/api/auth/status");
    // Seiten für Administratoren zeigen normalen Nutzern nur einen Hinweis.
    if (zustand.angemeldet && nurAdmin && !zustand.istAdmin) {
      document.getElementById("anmeldung").hidden = true;
      document.getElementById("geschuetzt").hidden = true;
      const bereich = document.getElementById("kein-zugriff");
      if (bereich) bereich.hidden = false;
      benutzerAnzeigen();
      return;
    }
    if (zustand.angemeldet) inhaltZeigen();
    else zeigen();
    benutzerAnzeigen();
  }

  function benutzerAnzeigen() {
    const feld = document.getElementById("angemeldet-als");
    if (!feld) return;
    feld.textContent = zustand && zustand.benutzer
      ? zustand.benutzer.name + " (" + zustand.benutzer.rolle + ")" : "";
    const knopf = document.getElementById("btn-abmelden");
    if (knopf) knopf.hidden = !(zustand && zustand.angemeldet);
  }

  function verdrahten() {
    document.getElementById("anmelde-formular").addEventListener("submit", async (e) => {
      e.preventDefault();
      const name = document.getElementById("f-name");
      const feld = document.getElementById("f-passwort");
      const anzeige = document.getElementById("anmelde-meldung");
      const erst = zustand && !zustand.eingerichtet;

      if (erst && feld.value !== document.getElementById("f-passwort2").value) {
        anzeige.textContent = "Die beiden Eingaben stimmen nicht überein.";
        return;
      }
      anzeige.textContent = "…";
      const daten = await senden(
        erst ? "/api/auth/einrichten" : "/api/auth/anmelden",
        { name: name.value, passwort: feld.value });
      if (!daten.ok) {
        anzeige.textContent = daten.fehler;
        return;
      }
      feld.value = "";
      anzeige.textContent = "";
      if (daten.token) {
        // Bei der Ersteinrichtung ist der Zugangsschlüssel nur jetzt sichtbar.
        window.alert("Konto angelegt.\n\nDein Zugangsschlüssel für VS Code:\n\n" +
          daten.token + "\n\nEr ist nur jetzt im Klartext zu sehen. " +
          "Unter /konto lässt sich jederzeit ein neuer erzeugen.");
      }
      await pruefen();
    });

    const abmelden = document.getElementById("btn-abmelden");
    if (abmelden) {
      abmelden.addEventListener("click", async () => {
        await senden("/api/auth/abmelden", {});
        zustand = await holen("/api/auth/status");
        zeigen();
        benutzerAnzeigen();
      });
    }
  }

  return {
    start(optionen) {
      nurAdmin = Boolean(optionen && optionen.nurAdmin);
      beiAnmeldung = optionen && optionen.beiAnmeldung;
      verdrahten();
      pruefen();
    },
    pruefen,
    zeigen,
    zustand: () => zustand,
  };
})();
