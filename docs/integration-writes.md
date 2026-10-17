# Integrationen kontrolliert verändern

Stand 17.10.2026: Schema 0043 ergänzt gesonderte Schreibrechte pro Profil,
gebundene Aktionsfreigaben, dauerhafte Dispatchbelege und lesenden Abgleich.
Release 148e921 / Schema 0043 ist auf der Test-VM installiert. SSH-Anmeldung,
eine echte verwaltete Datei, Hashprüfung, Beleg-Replay und Bereinigung sind live
geprüft. Ein realer lokaler KI-Entwurf mit explizitem Dateinamen/Inhalt war gültig;
ein vorheriger ungültiger Entwurf löste keine Aktion aus. HA, Paperless, UniFi und
MCP sind synthetisch geprüft und haben noch keine echte Zielschreibabnahme.
Implementierung und reale Abnahme bleiben getrennte Nachweise.

Die Zugangsdaten brauchen zusätzlich die passenden Rechte im Zielsystem.
Die obdaAI-Freigabe erweitert keine externen Konto- oder Dateisystemrechte.

Unter **Einstellungen → Integrationen → Änderungen** zunächst Schreibaktionen
für das konkrete Profil erlauben. Aktivierung des Verbindungsprofils allein
gewährt keine Schreibrechte. Die globale Gateway-Schreibpause bleibt zusätzlich
verbindlich. Nach dem Aufheben der Pause eine neue Vorschau vorbereiten.

1. Eine unterstützte Aktion auswählen und Ziel/Werte eingeben. Optional entwirft
   die lokale KI die Parameter aus einer Beschreibung. Fehlende IDs sollen als
   Rückfrage erscheinen. Kein Entwurf führt selbst etwas aus.
2. „Änderung vorbereiten“ liest den aktuellen Zielzustand und speichert einen
   unveränderlichen Vorschlag mit Profilrevision, Aktion, Parametern und Zustandshash.
3. Die genaue Vorschau prüfen. „Diese Änderung freigeben und ausführen“ erteilt
   eine fünfminütige Freigabe für genau diesen Vorschlag und startet einen Versuch.
4. Der Ausführungsbeleg hält Vorher-/Nachherzustand und Ergebnis lokal fest.
   Frühere Aufträge bleiben nach Neuladen in der Historie sichtbar.

## Tatsächlich implementierte Operationen

| Profil | Schreibaktionen | Grenze |
|---|---|---|
| Home Assistant | Licht, Switch, Fan und Input Boolean ein/aus; Input Number/Number setzen; Input Select/Select auswählen | Konkrete Entity-ID; keine beliebigen Services, Automationen, Skripte, Updates oder Restoreaktionen |
| Paperless | Titel, Tags, Korrespondent und Dokumenttyp eines konkreten Dokuments | Keine Originaländerung, Uploads, Löschung oder Berechtigungsänderung |
| SSH | UTF-8-Textdatei per SFTP schreiben; bestehende Datei davor sichern | Eigener Ordner `~/obdaai-managed`, einfacher `.txt`-Name, höchstens 100.000 Zeichen; keine Shell oder Modellprogramme |
| UniFi | Einem konkreten Gastclient zeitlich begrenzten Zugang geben oder entziehen | Offizielle lokale Network Integration API; kein Firewall-, WLAN-, Routing- oder Controllerumbau |
| MCP | Einzelnen ausdrücklich ausgewählten Toolaufruf mit aktuellem Schema und konkreten Parametern freigeben | Unterstütztes geschlossenes JSON-Schema-Subset; keine Rechte aus Annotationen, kein importierter Code, keine automatischen Modell-Toolschleifen |
| SMTP | Ergebnis nach Vorschau ausdrücklich senden | Bestehender separater Mailversand unter Use Cases; kein beliebiger Versand aus dem neuen Gateway |

Das ist kein vollständiger administrativer Zugriff auf alle Funktionen der
Zielsysteme. Weitere Aktionen benötigen eigene geprüfte Verträge und Abnahmen.
Der allgemeine Chat und Aufgaben führen die neuen Schreiboperationen noch nicht
autonom aus. Die lokale KI-Vorbereitung ist im Änderungsdialog verfügbar; MCP-
Argumente werden vom Menschen nach Schemaprüfung eingetragen.

UniFi-Profile müssen auf den lokalen Integration-API-Basispfad zeigen, z.B.
`https://controller.example/proxy/network/integration`. UUIDs für Site und Client
stammen aus dem eigenen Controller. Die Guest-API ist kein allgemeines Blockieren
beliebiger LAN-Clients. SSH unterstützt private Schlüssel/Passwort und optionale
OpenSSH-Benutzerzertifikate; die Hostidentität wird vor Anmeldung geprüft.

## Fehler, Wiederholung und Gleichzeitigkeit

Ein Ausführungsintent wird **vor** dem möglichen externen Effekt committed.
Dieselbe Aktions-ID löst höchstens einen Dispatchversuch aus. Nach Timeout,
Prozessabbruch oder unklarem Nachherzustand gibt es keinen automatischen Retry.
„Ergebnis lesend abgleichen“ sendet keine Änderung. Ein passender Zustand belegt
das beobachtete Ergebnis, nicht sicher dessen Verursachung durch den ersten Aufruf.
MCP-Kataloggleichheit belegt keinen externen Effekt; unklare Toolaufrufe bleiben
unklar und benötigen Prüfung im Zielsystem.

Profilrevision, Schreibfreigabe, Datenschutzklasse, Toolrevision, globale Pause,
Widerruf, Ablauf und Parameterhash werden unmittelbar vor Dispatch nochmals geprüft.
PostgreSQL sperrt die Registry und Policy über diesen letzten Übergang. Die
externen APIs bieten nicht überall atomare Compare-and-set-Operationen; zwischen
lesender Prüfung und externem Effekt kann ein fremder Client den Zielzustand ändern.
Eine globale Exactly-once-/Transaktionszusage über Fremdsysteme besteht nicht.

Zugangsdaten bleiben verschlüsselt in der bestehenden Registry. Die lokale
KI erhält nur den eingegebenen Auftrag und das feste Argumentschema, keine
Credentials, gespeicherte Profilwerte, Altchats oder automatisch gelesene Quellen.
Entwürfe verwenden die normale dauerhafte Run-/Budget-/Providerprüfung und bleiben
LOCAL_ONLY. Änderungen am Profil blockieren die Weiterverwendung des Entwurfs.
Prüf- und Aktionsbelege sind private Laufzeitdaten; öffentliche Bilder nur synthetisch.

Protokollgrundlagen: [Home Assistant REST](https://contributors.home-assistant.io/core/internals/rest-api/),
[Paperless API](https://github.com/paperless-ngx/paperless-ngx/blob/main/docs/api.md),
[UniFi Network OpenAPI](https://developer.ui.com/network/v10.6.106/openapi.json),
[Paramiko SFTP](https://docs.paramiko.org/en/stable/api/sftp.html),
[MCP Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).
