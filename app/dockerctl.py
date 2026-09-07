"""Steuerung des Ollama-Containers ueber die Docker-Engine-API.

Die API wird direkt ueber den Unix-Socket angesprochen (kein Docker-CLI und
keine Fremdbibliothek noetig). Dafuer muss /var/run/docker.sock in das
Portal gemountet sein.

Wichtig: Der Containername kommt ausschliesslich aus der Konfiguration des
Portals, nie aus der Anfrage des Browsers. Damit kann ueber das Portal kein
beliebiger Container des Hosts gesteuert werden.
"""

import http.client
import json
import socket
import time
from datetime import datetime, timezone

from . import config

API_VERSION = "v1.44"

# Diese Umgebungsvariablen werden auf der Betriebsseite angezeigt.
INTERESSANTE_VARS = [
    "OLLAMA_NUM_PARALLEL",
    "OLLAMA_CONTEXT_LENGTH",
    "OLLAMA_KV_CACHE_TYPE",
    "OLLAMA_MAX_LOADED_MODELS",
    "OLLAMA_HOST",
    "OLLAMA_KEEP_ALIVE",
    "OLLAMA_FLASH_ATTENTION",
]

# Beim Neuerstellen uebernommene Felder aus der Container-Konfiguration.
CONFIG_FELDER = [
    "Image", "Cmd", "Entrypoint", "WorkingDir", "User", "Labels",
    "ExposedPorts", "Volumes", "Tty", "OpenStdin", "StdinOnce",
    "AttachStdin", "AttachStdout", "AttachStderr", "Healthcheck",
    "Domainname", "StopSignal", "StopTimeout", "Shell",
]


class DockerFehler(Exception):
    """Fehler bei der Kommunikation mit der Docker-Engine."""


class _UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP ueber einen Unix-Socket statt ueber TCP."""

    def __init__(self, socket_pfad, timeout):
        super().__init__("localhost", timeout=timeout)
        self.socket_pfad = socket_pfad

    def connect(self):
        verbindung = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        verbindung.settimeout(self.timeout)
        verbindung.connect(self.socket_pfad)
        self.sock = verbindung


def _api(methode, pfad, payload=None, timeout=None, roh=False):
    """Ruft die Docker-API auf. Liefert geparstes JSON oder rohe Bytes."""
    verbindung = _UnixHTTPConnection(config.DOCKER_SOCKET,
                                     timeout or config.DOCKER_TIMEOUT)
    kopf = {"Accept": "application/json"}
    rumpf = None
    if payload is not None:
        rumpf = json.dumps(payload).encode("utf-8")
        kopf["Content-Type"] = "application/json"
    try:
        verbindung.request(methode, f"/{API_VERSION}{pfad}", body=rumpf, headers=kopf)
        antwort = verbindung.getresponse()
        daten = antwort.read()
    except FileNotFoundError:
        raise DockerFehler(
            f"Docker-Socket {config.DOCKER_SOCKET} nicht gefunden. Im Container muss "
            "'/var/run/docker.sock:/var/run/docker.sock' gemountet sein.")
    except PermissionError:
        raise DockerFehler(
            f"Keine Berechtigung fuer {config.DOCKER_SOCKET}. Das Portal muss in der "
            "Gruppe 'docker' laufen (group_add in der docker-compose.yml).")
    except (socket.timeout, TimeoutError):
        raise DockerFehler(f"Zeitueberschreitung bei der Docker-API ({methode} {pfad}).")
    except OSError as exc:
        raise DockerFehler(f"Docker-API nicht erreichbar: {exc}")
    finally:
        verbindung.close()

    if antwort.status >= 400:
        meldung = daten.decode("utf-8", "replace")[:400]
        try:
            meldung = json.loads(meldung).get("message", meldung)
        except (json.JSONDecodeError, AttributeError):
            pass
        raise DockerFehler(f"Docker meldet HTTP {antwort.status}: {meldung}")

    if roh:
        return daten
    if not daten:
        return None
    return json.loads(daten.decode("utf-8", "replace"))


# ------------------------------------------------------------------ Status
def _env_dict(liste):
    ergebnis = {}
    for eintrag in liste or []:
        name, _, wert = eintrag.partition("=")
        ergebnis[name] = wert
    return ergebnis


def _laufzeit(gestartet_iso):
    """Wandelt den Startzeitpunkt in eine lesbare Laufzeit um."""
    try:
        gestartet = datetime.fromisoformat(gestartet_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return ""
    sekunden = int((datetime.now(timezone.utc) - gestartet).total_seconds())
    if sekunden < 0:
        return ""
    tage, rest = divmod(sekunden, 86400)
    stunden, rest = divmod(rest, 3600)
    minuten = rest // 60
    if tage:
        return f"{tage} d {stunden} h"
    if stunden:
        return f"{stunden} h {minuten} min"
    return f"{minuten} min"


def _statistik():
    """Momentaufnahme von CPU- und Speicherverbrauch (optional)."""
    try:
        daten = _api("GET", f"/containers/{config.CONTAINER_NAME}/stats?stream=false",
                     timeout=15)
    except DockerFehler:
        return None
    try:
        cpu = daten["cpu_stats"]
        vorher = daten["precpu_stats"]
        delta = cpu["cpu_usage"]["total_usage"] - vorher["cpu_usage"]["total_usage"]
        system = cpu.get("system_cpu_usage", 0) - vorher.get("system_cpu_usage", 0)
        kerne = cpu.get("online_cpus") or len(
            cpu["cpu_usage"].get("percpu_usage") or [1])
        prozent = (delta / system) * kerne * 100 if system > 0 else 0.0
        speicher = daten.get("memory_stats", {})
        benutzt = speicher.get("usage", 0) - speicher.get("stats", {}).get("cache", 0)
        return {
            "cpuProzent": round(prozent, 1),
            "ramGib": round(benutzt / 1024 ** 3, 2),
            "ramLimitGib": round(speicher.get("limit", 0) / 1024 ** 3, 2),
        }
    except (KeyError, TypeError, ZeroDivisionError):
        return None


def status(mit_statistik=True):
    """Liefert den Zustand des Ollama-Containers."""
    daten = _api("GET", f"/containers/{config.CONTAINER_NAME}/json")
    zustand = daten.get("State", {})
    conf = daten.get("Config", {})
    host = daten.get("HostConfig", {})
    umgebung = _env_dict(conf.get("Env"))

    gpus = []
    for anforderung in host.get("DeviceRequests") or []:
        if "gpu" in (anforderung.get("Driver") or "").lower() or \
                any("gpu" in str(f).lower() for f in anforderung.get("Capabilities") or []):
            anzahl = anforderung.get("Count")
            geraete = anforderung.get("DeviceIDs") or []
            gpus.append("alle" if anzahl == -1 else (", ".join(geraete) or str(anzahl)))

    ergebnis = {
        "name": daten.get("Name", "").lstrip("/"),
        "id": daten.get("Id", "")[:12],
        "image": conf.get("Image", ""),
        "status": zustand.get("Status", "unbekannt"),
        "laeuft": bool(zustand.get("Running")),
        "gesundheit": (zustand.get("Health") or {}).get("Status", ""),
        "exitCode": zustand.get("ExitCode"),
        "gestartet": zustand.get("StartedAt", ""),
        "laufzeit": _laufzeit(zustand.get("StartedAt", "")) if zustand.get("Running") else "",
        "neustartRegel": (host.get("RestartPolicy") or {}).get("Name", ""),
        "neustartZaehler": daten.get("RestartCount", 0),
        "gpu": ", ".join(gpus) if gpus else "keine GPU zugewiesen",
        "einstellungen": {name: umgebung.get(name, "") for name in INTERESSANTE_VARS},
        "portalDarfSteuern": config.DOCKER_STEUERUNG,
        "compose": bool((conf.get("Labels") or {}).get("com.docker.compose.project")),
    }
    if mit_statistik and ergebnis["laeuft"]:
        ergebnis["statistik"] = _statistik()
    return ergebnis


def logs(zeilen=200):
    """Liest die letzten Log-Zeilen des Containers."""
    zeilen = max(1, min(int(zeilen), 2000))
    roh = _api("GET",
               f"/containers/{config.CONTAINER_NAME}/logs"
               f"?stdout=1&stderr=1&tail={zeilen}&timestamps=0",
               roh=True, timeout=30)
    return _entwirre_logs(roh)


def _entwirre_logs(roh):
    """Entfernt die 8-Byte-Rahmen des gemultiplexten Docker-Log-Streams."""
    if not roh:
        return ""
    # Ohne TTY rahmt Docker jede Ausgabe: [Typ, 0,0,0, Laenge(4 Byte big endian)]
    if roh[0] not in (0, 1, 2):
        return roh.decode("utf-8", "replace")
    teile = []
    pos = 0
    while pos + 8 <= len(roh):
        laenge = int.from_bytes(roh[pos + 4:pos + 8], "big")
        teile.append(roh[pos + 8:pos + 8 + laenge])
        pos += 8 + laenge
    return b"".join(teile).decode("utf-8", "replace")


# ----------------------------------------------------------------- Aktionen
def aktion(name):
    """Startet, stoppt oder startet den Container neu."""
    pfade = {
        "start": "/start",
        "stopp": "/stop?t=30",
        "neustart": "/restart?t=30",
    }
    if name not in pfade:
        raise DockerFehler(f"Unbekannte Aktion: {name}")
    _api("POST", f"/containers/{config.CONTAINER_NAME}{pfade[name]}", timeout=90)
    return {"ok": True, "aktion": name}


# ------------------------------------------------- Einstellungen uebernehmen
def _neue_env(alt, aenderungen):
    """Setzt die geaenderten Variablen, laesst alle uebrigen unangetastet."""
    umgebung = _env_dict(alt)
    umgebung.update({k: str(v) for k, v in aenderungen.items()})
    return [f"{name}={wert}" for name, wert in umgebung.items()]


def _erstellungs_payload(daten, env):
    """Baut aus einem Inspect-Ergebnis die Vorlage fuer einen neuen Container."""
    conf = daten.get("Config", {})
    payload = {feld: conf[feld] for feld in CONFIG_FELDER if conf.get(feld) is not None}
    payload["Env"] = env
    payload["HostConfig"] = daten.get("HostConfig", {})

    # Hostname nur uebernehmen, wenn er nicht die Container-ID ist.
    hostname = conf.get("Hostname") or ""
    if hostname and not daten.get("Id", "").startswith(hostname):
        payload["Hostname"] = hostname

    netze = (daten.get("NetworkSettings") or {}).get("Networks") or {}
    # Beim Erstellen nur das erste Netz angeben; weitere werden danach
    # verbunden, weil aeltere API-Versionen nur eines akzeptieren.
    erstes = {}
    weitere = []
    for index, (netzname, endpunkt) in enumerate(netze.items()):
        schlank = {schluessel: endpunkt.get(schluessel)
                   for schluessel in ("Aliases", "IPAMConfig", "Links")
                   if endpunkt.get(schluessel)}
        if index == 0:
            erstes = {netzname: schlank}
        else:
            weitere.append((netzname, schlank))
    if erstes:
        payload["NetworkingConfig"] = {"EndpointsConfig": erstes}
    return payload, weitere


def _alte_sicherungen_aufraeumen(basisname, behalten):
    """Loescht aeltere Sicherungscontainer, damit sich nichts anhaeuft."""
    try:
        vorhandene = _api("GET", "/containers/json?all=1") or []
    except DockerFehler:
        return
    kandidaten = []
    for eintrag in vorhandene:
        for roher_name in eintrag.get("Names") or []:
            name = roher_name.lstrip("/")
            if name.startswith(f"{basisname}-vorher-") and name != behalten:
                kandidaten.append((eintrag.get("Created", 0), eintrag["Id"]))
    for _, container_id in sorted(kandidaten, reverse=True):
        try:
            _api("DELETE", f"/containers/{container_id}?force=1&v=0", timeout=60)
        except DockerFehler:
            pass


def einstellungen_uebernehmen(aenderungen):
    """Erstellt den Container mit neuen Umgebungsvariablen neu.

    Docker kann die Umgebung eines bestehenden Containers nicht aendern.
    Der Container wird daher gestoppt, umbenannt (als Sicherung) und mit
    identischer Konfiguration, aber neuer Umgebung neu angelegt. Schlaegt
    der Start fehl, wird der alte Container wiederhergestellt.
    """
    daten = _api("GET", f"/containers/{config.CONTAINER_NAME}/json")
    alte_id = daten["Id"]
    name = daten.get("Name", "").lstrip("/")
    lief = bool(daten.get("State", {}).get("Running"))
    env = _neue_env(daten.get("Config", {}).get("Env"), aenderungen)
    payload, weitere_netze = _erstellungs_payload(daten, env)

    sicherungsname = f"{name}-vorher-{time.strftime('%Y%m%d-%H%M%S')}"
    protokoll = []

    if lief:
        _api("POST", f"/containers/{alte_id}/stop?t=30", timeout=90)
        protokoll.append("Alten Container gestoppt")

    _api("POST", f"/containers/{alte_id}/rename?name={sicherungsname}")
    protokoll.append(f"Alten Container als '{sicherungsname}' gesichert")

    try:
        neu = _api("POST", f"/containers/create?name={name}", payload, timeout=60)
        neue_id = neu["Id"]
        protokoll.append("Neuen Container erstellt")
        for netzname, endpunkt in weitere_netze:
            _api("POST", f"/networks/{netzname}/connect",
                 {"Container": neue_id, "EndpointConfig": endpunkt})
            protokoll.append(f"Mit Netzwerk '{netzname}' verbunden")
        _api("POST", f"/containers/{neue_id}/start", timeout=90)
        protokoll.append("Neuen Container gestartet")
    except DockerFehler as fehler:
        # Rueckbau: neuen Container entfernen, alten zurueckbenennen und starten.
        rueckbau = []
        try:
            _api("DELETE", f"/containers/{name}?force=1&v=0", timeout=60)
            rueckbau.append("neuen Container entfernt")
        except DockerFehler:
            pass
        try:
            _api("POST", f"/containers/{alte_id}/rename?name={name}")
            rueckbau.append("alten Container zurueckbenannt")
            if lief:
                _api("POST", f"/containers/{alte_id}/start", timeout=90)
                rueckbau.append("alten Container wieder gestartet")
        except DockerFehler as rueckbau_fehler:
            rueckbau.append(f"ACHTUNG - Wiederherstellung fehlgeschlagen: {rueckbau_fehler}")
        raise DockerFehler(
            f"Uebernahme fehlgeschlagen: {fehler} | Wiederherstellung: "
            + ", ".join(rueckbau))

    _alte_sicherungen_aufraeumen(name, sicherungsname)
    return {
        "ok": True,
        "protokoll": protokoll,
        "sicherung": sicherungsname,
        "compose": bool((daten.get("Config", {}).get("Labels") or {})
                        .get("com.docker.compose.project")),
    }


# ------------------------------------------------------------------- Exec
def ausfuehren(befehl, timeout=15):
    """Fuehrt einen Befehl im Ollama-Container aus und liefert die Ausgabe.

    Wird gebraucht, um im Container /proc/net/tcp zu lesen - daraus ergibt
    sich, wie viele Verbindungen gerade offen sind.
    """
    erzeugt = _api("POST", f"/containers/{config.CONTAINER_NAME}/exec", {
        "AttachStdout": True,
        "AttachStderr": True,
        "Tty": False,
        "Cmd": befehl,
    }, timeout=timeout)
    roh = _api("POST", f"/exec/{erzeugt['Id']}/start",
               {"Detach": False, "Tty": False}, timeout=timeout, roh=True)
    return _entwirre_logs(roh)


def ollama_port():
    """Port, auf dem Ollama INNERHALB des Containers lauscht."""
    try:
        daten = _api("GET", f"/containers/{config.CONTAINER_NAME}/json")
        host = _env_dict(daten.get("Config", {}).get("Env")).get("OLLAMA_HOST", "")
    except DockerFehler:
        return 11434
    if ":" in host:
        try:
            return int(host.rsplit(":", 1)[1])
        except ValueError:
            pass
    return 11434
