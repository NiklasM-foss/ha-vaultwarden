# Vaultwarden für Home Assistant

Custom-Integration, die eine bestehende [Vaultwarden](https://github.com/dani-garcia/vaultwarden)-Instanz
in Home Assistant überwacht. **Kein Add-on** – Vaultwarden läuft weiter dort, wo es
läuft (LXC, Docker, VM, anderer Server), die Integration fragt es nur über HTTP ab.

Es werden ausschließlich Zustandsdaten gelesen. Passwörter, Tresoreinträge und
Schlüsselmaterial verlassen Vaultwarden nicht und landen nirgends in Home Assistant.

## Entities

Ohne Admin-Token:

| Entity | Typ | Beschreibung |
| --- | --- | --- |
| Erreichbar | `binary_sensor` (connectivity) | Antwortet `/api/alive`? Der Endpunkt öffnet serverseitig auch die Datenbank, prüft also mehr als nur den Port. |
| Version | `sensor` | Installierte Vaultwarden-Version aus `/api/version`. |
| Serverzeit | `sensor` (Zeitstempel, standardmäßig deaktiviert) | Uhrzeit laut Server, praktisch zum Aufspüren von Zeitdrift. |

Zusätzlich mit Admin-Token:

| Entity | Typ | Beschreibung |
| --- | --- | --- |
| Benutzer | `sensor` | Anzahl Konten, mit Attribut `benutzer` (Name, Mail, aktiviert, 2FA, letzte Aktivität). |
| Benutzer aktiviert / deaktiviert | `sensor` | Aufteilung nach `userEnabled`. |
| Benutzer mit 2FA | `sensor` | Konten mit hinterlegtem zweiten Faktor. |
| Benutzer eingeladen | `sensor` | Eingeladene, noch nicht abgeschlossene Konten. |
| Organisationen | `sensor` | Anzahl Organisationen. |
| Letzte Aktivität | `sensor` (Zeitstempel) | Jüngster Login/Zugriff über alle Konten. |
| Neueste Version | `sensor` | Aktuellste veröffentlichte Version laut Diagnose-Seite. |
| Server / Web-Vault | `update` | Zeigt an, ob ein Update verfügbar ist. Installiert wird aus Home Assistant heraus nichts. |

## Installation

### HACS

1. HACS → Integrationen → Menü oben rechts → *Benutzerdefinierte Repositories*
2. Repository `https://github.com/NiklasM-foss/ha-vaultwarden`, Kategorie *Integration*
3. „Vaultwarden" installieren, Home Assistant neu starten

### Manuell

Ordner `custom_components/vaultwarden` nach `<config>/custom_components/vaultwarden`
kopieren und Home Assistant neu starten.

## Einrichtung

*Einstellungen → Geräte & Dienste → Integration hinzufügen → Vaultwarden*

| Feld | Bedeutung |
| --- | --- |
| URL | z. B. `http://192.168.1.10` oder `https://vault.example.com`. Fehlt das Schema, wird `http://` ergänzt. |
| Admin-Token | Optional. Der Wert der Umgebungsvariable `ADMIN_TOKEN` der Vaultwarden-Instanz. Ohne Token gibt es nur die drei Basis-Entities. |
| SSL-Zertifikat prüfen | Bei selbstsigniertem Zertifikat abschalten. |

Unter *Konfigurieren* lässt sich später das Abfrageintervall ändern (Standard 5 Minuten).
Wird das Token ungültig, fragt Home Assistant über den normalen Reauth-Dialog nach einem neuen.

### Admin-Token

Ist `ADMIN_TOKEN` nicht gesetzt, ist das Admin-Backend deaktiviert und die
Integration meldet das bei der Einrichtung. Ein Token erzeugen:

```bash
openssl rand -base64 48
```

Als Argon2-Hash (empfohlen, dann steht das Token nicht im Klartext in der Config)
funktioniert es ebenfalls – die Integration meldet sich mit dem Klartext-Token an,
Vaultwarden prüft es gegen den Hash.

## Wie die Daten geholt werden

Vaultwarden hat keine Monitoring-API, deshalb drei Quellen:

* `/api/version` und `/api/alive` sind ohne Anmeldung erreichbar.
* `/admin/users` liefert JSON, benötigt aber eine Anmeldung. Die läuft über
  `POST /admin` mit dem Token als Formularfeld; Vaultwarden setzt daraufhin das
  Cookie `VW_ADMIN` (ein JWT). Header- oder Bearer-Auth gibt es nicht. Das Cookie
  läuft nach `ADMIN_SESSION_LIFETIME` (Standard 20 Minuten) ab, die Integration
  meldet sich dann automatisch neu an.
* Versionsvergleich und Organisationen gibt es nur als HTML-Seite. Daraus werden
  gezielt einzelne Werte gelesen (die Element-IDs bzw. Marker, die Vaultwarden für
  sein eigenes JavaScript vergibt). Ändert sich das Template, bleibt der jeweilige
  Wert leer, statt eine falsche Zahl zu liefern.

Weil Vaultwarden für die Diagnose-Seite selbst GitHub und einen NTP-Server
kontaktiert, wird sie unabhängig vom Abfrageintervall höchstens einmal pro Stunde
geladen.

Ein nicht erreichbarer Server ist kein Update-Fehler, sondern ein Messwert: die
übrigen Entities werden „nicht verfügbar", `binary_sensor` **Erreichbar** bleibt
aber bedienbar und geht auf `off`.

## Beispiel-Automation

Meldung, wenn der Tresor nicht mehr antwortet:

```yaml
alias: Vaultwarden offline
triggers:
  - trigger: state
    entity_id: binary_sensor.vaultwarden_erreichbar
    to: "off"
    for: "00:05:00"
actions:
  - action: notify.persistent_notification
    data:
      message: "Vaultwarden antwortet seit 5 Minuten nicht mehr."
```

## Lizenz

MIT
