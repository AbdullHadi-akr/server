"use strict";

let rollen = ["nutzer", "admin"];

function tokenZeigen(ziel, name, token) {
  ziel.textContent = "";
  const karte = el("div", "karte");
  karte.appendChild(el("h4", null, "Zugangsschlüssel für " + name));
  const feld = el("div", "codebox");
  const knopf = el("button", "kopieren", "Kopieren");
  knopf.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(token);
      knopf.textContent = "Kopiert ✓";
    } catch (fehler) {
      knopf.textContent = "Kopieren nicht möglich";
    }
  });
  const pre = el("pre", null, token);
  feld.appendChild(knopf);
  feld.appendChild(pre);
  karte.appendChild(feld);
  karte.appendChild(el("p", "tipp",
    "→ Jetzt weitergeben und in VS Code eintragen. Der Schlüssel ist nur hier " +
    "und nur jetzt im Klartext zu sehen."));
  ziel.appendChild(karte);
}

async function listeLaden() {
  const ziel = document.getElementById("benutzer-liste");
  const daten = await holen("/api/benutzer");
  ziel.textContent = "";
  if (!daten.ok) {
    ziel.appendChild(el("p", "detail", daten.fehler));
    return;
  }
  rollen = daten.rollen;

  const huelle = el("div", "tabellenhuelle");
  const tabelle = el("table", "modelle");
  const kopf = el("tr");
  ["Benutzer", "Rolle", "Zustand", "Angelegt", "Letzte Anmeldung", ""]
    .forEach((t) => kopf.appendChild(el("th", null, t)));
  tabelle.appendChild(kopf);

  daten.benutzer.forEach((b) => {
    const zeile = el("tr");
    zeile.appendChild(el("td", "name", b.name));

    const rollenfeld = el("td");
    const auswahl = el("select");
    rollen.forEach((r) => {
      const eintrag = el("option", null, r);
      eintrag.value = r;
      if (r === b.rolle) eintrag.selected = true;
      auswahl.appendChild(eintrag);
    });
    auswahl.addEventListener("change", async () => {
      const antwort = await senden("/api/benutzer/aendern",
        { id: b.id, rolle: auswahl.value });
      if (!antwort.ok) window.alert(antwort.fehler);
      listeLaden();
    });
    rollenfeld.appendChild(auswahl);
    zeile.appendChild(rollenfeld);

    zeile.appendChild(el("td", null, b.aktiv ? "aktiv" : "gesperrt"));
    zeile.appendChild(el("td", null, b.erstellt));
    zeile.appendChild(el("td", null, b.letzterLogin || "–"));

    const knoepfe = el("td");
    const sperren = el("button", null, b.aktiv ? "Sperren" : "Freigeben");
    sperren.addEventListener("click", async () => {
      const antwort = await senden("/api/benutzer/aendern",
        { id: b.id, aktiv: !b.aktiv });
      if (!antwort.ok) window.alert(antwort.fehler);
      listeLaden();
    });

    const neuerSchluessel = el("button", null, "Neuer Schlüssel");
    neuerSchluessel.addEventListener("click", async () => {
      if (!window.confirm("Der bisherige Schlüssel von " + b.name +
          " wird sofort ungültig. Fortfahren?")) return;
      const antwort = await senden("/api/benutzer/token", { id: b.id });
      if (antwort.ok) {
        tokenZeigen(document.getElementById("neuer-token"), b.name, antwort.token);
      } else {
        window.alert(antwort.fehler);
      }
    });

    const passwort = el("button", null, "Passwort setzen");
    passwort.addEventListener("click", async () => {
      const neu = window.prompt("Neues Passwort für " + b.name + ":");
      if (!neu) return;
      const antwort = await senden("/api/benutzer/passwort",
        { id: b.id, passwort: neu });
      window.alert(antwort.ok ? "Passwort gesetzt." : antwort.fehler);
    });

    const loeschen = el("button", null, "Löschen");
    loeschen.addEventListener("click", async () => {
      if (!window.confirm(b.name + " endgültig löschen?")) return;
      const antwort = await senden("/api/benutzer/loeschen", { id: b.id });
      if (!antwort.ok) window.alert(antwort.fehler);
      listeLaden();
    });

    [sperren, neuerSchluessel, passwort, loeschen].forEach((k) => knoepfe.appendChild(k));
    zeile.appendChild(knoepfe);
    tabelle.appendChild(zeile);
  });
  huelle.appendChild(tabelle);
  ziel.appendChild(huelle);
}

document.getElementById("anlegen-formular").addEventListener("submit", async (e) => {
  e.preventDefault();
  const anzeige = document.getElementById("anlegen-meldung");
  anzeige.textContent = "…";
  const daten = await senden("/api/benutzer/anlegen", {
    name: document.getElementById("f-neuer-name").value,
    passwort: document.getElementById("f-neues-passwort").value,
    rolle: document.getElementById("f-rolle").value,
  });
  if (!daten.ok) {
    anzeige.textContent = daten.fehler;
    return;
  }
  anzeige.textContent = "Angelegt.";
  document.getElementById("f-neuer-name").value = "";
  document.getElementById("f-neues-passwort").value = "";
  tokenZeigen(document.getElementById("neuer-token"), daten.benutzer.name, daten.token);
  listeLaden();
});

versionAnzeigen();
seiteAbsichern({ nurAdmin: true, beiZugang: listeLaden });
