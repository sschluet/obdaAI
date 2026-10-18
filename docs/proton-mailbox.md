# Proton Mail: Postfachzugriff über Bridge und MCP

Proton Bridge stellt IMAP für das Postfach und SMTP für den Versand bereit.
Ein kostenpflichtiger Proton-Mail-Tarif ist erforderlich. Ein SMTP-Profil allein
ermöglicht keinen Postfachzugriff. Die geprüften Community-MCPs ergänzen Bridge;
sie ersetzen den offiziellen Proton-Zugang nicht.

In der privaten Testumgebung läuft die offizielle Bridge 3.27.1; Signatur und
tatsächlich ausgeführte Programmdatei sind unabhängig geprüft. Das ursprüngliche
Installationspaket 3.22.0 wurde zusätzlich mit `debsig-verify` geprüft. Als
Postfachadapter wurde `mhbxyz/protonmail-mcp` 0.4.0 gewählt. Dessen Quellstand
`f15d769d562de55c288a574f2a1e0946fefc9e31`, veröffentlichtes Wheel und sämtliche
Laufzeitabhängigkeiten sind festgeschrieben und hashgeprüft. 255 Tests des
Community-Projekts sowie ein synthetischer Katalogtest mit allen drei von obdaAI
unterstützten MCP-Protokollen sind erfolgreich. Das ist kein Nachweis eines
angemeldeten echten Postfachs.

Bridge und MCP laufen mit getrennten Dienstkonten. IMAP und SMTP binden nur an
Loopback. Der MCP verlangt ein Bearer-Token und bleibt im serverseitigen Modus
`read`; Versand und Postfachänderungen sind gesperrt. Die von diesem Server auch
angebotenen lokalen Exportwerkzeuge werden nicht als reine Lesewerkzeuge in
obdaAI freigegeben. Anmeldedaten, Pfade und private Netzwerkziele bleiben außerhalb
von Git. obdaAI verwendet ausschließlich den gesonderten Bridge-Zugang.

## Postfach unter Integrationen einrichten

Öffne Einstellungen → Integrationen → **Verbindung hinzufügen** → **Proton Mail**.
Der Assistent führt in drei Schritten durch die Einrichtung:

1. **Vorbereiten:** Ein kostenpflichtiger Tarif und die auf dem Server vorbereitete
   Bridge sind erforderlich. Unter **Noch keine Bridge-Zugangsdaten?** wird erklärt,
   wie du mit dem Betreiber über dessen privaten Serverzugang dein Proton-Konto
   direkt in Bridge anmeldest. Die offizielle Proton-Anleitung ist verlinkt.
   Kontoanmeldung und gegebenenfalls 2FA erfolgen weiterhin außerhalb von obdaAI.
2. **Zugangsdaten:** Trage den Namen der Verbindung, den **Bridge-Benutzernamen**
   und das von Bridge erzeugte **Bridge-Passwort** für Mailprogramme ein. Wähle,
   ob du lokales Lesen und Suchen in Chat, Aufgaben und Projekten erlaubst.
   Vorhandene Verbindungen starten direkt in diesem Schritt.
3. **Prüfen und verbinden:** Kontrolliere die Zusammenfassung. Erst der Klick auf
   **Verbindung prüfen und speichern** startet die Prüfung; ein Wechsel zwischen
   den Schritten kontaktiert das Postfach nicht. Nach Erfolg schließt **Fertig**
   den Assistenten.

**Verbindung prüfen und speichern** prüft den Zugang und den MCP-Katalog. Die
Option **Lokales Lesen und Suchen über Chat, Aufgaben und Projekte erlauben**
erteilt ausschließlich die acht unten genannten Lesefreigaben für dieses Profil.
Profil-Schreibrechte, allgemeiner MCP-Vollzugriff und autonome Änderungen bleiben
ausgeschaltet; die Grenze für Änderungen beträgt null. Die Verbindung kann danach
im Chat, einer Aufgabe oder einem Projekt ausgewählt werden.

Ein leeres Passwortfeld behält den gespeicherten Bridge-Zugang nur bei unverändertem
Benutzernamen. Das Passwort erscheint weder in der Statusantwort noch als Klartext
im Formular und wird nach Erfolg oder Fehler aus dem Eingabefeld entfernt. Nach
einem fehlgeschlagenen Versuch lädt die Oberfläche den aktuellen Stand; ein
weiterer Versuch benötigt einen neuen ausdrücklichen Klick.

Die Einrichtung verwendet einen separaten, rootverwalteten lokalen Broker. Dieser
akzeptiert nur die feste Bridge-Konfiguration, prüft STARTTLS gegen das gepinnte
Bridge-Zertifikat und öffnet den Posteingang mit IMAP ausdrücklich lesend. Er kann
nur die Bridge-Zugangsdaten und den festgelegten lesenden MCP-Dienst konfigurieren;
ein frei wählbares Ziel oder ein Shellbefehl gehört nicht zu dieser Schnittstelle.
Revisionen, Anfragekennung und vorab gespeicherter Einrichtungszustand verhindern
blinde Wiederholung nach unklarem Ausgang. Alte Profilrechte werden vor einem
Zugangswechsel entzogen. Die Einrichtung verschickt keine Nachricht und verändert
keine Postfachinhalte.

## Gezielte MCP-Lesefreigaben

Die kompakte Integrationsübersicht führt über **KI-Zugriff** zu **Kein KI-Zugriff**,
**Nur lesen** und **Änderungen erlauben**. Vorhandene Einzelrechte bleiben beim
Öffnen erhalten; eine Auswahl erzeugt keine zusätzlichen Werkzeug- oder Zielrechte.
Eine ausdrücklich geänderte Zugriffsauswahl schaltet autonome Ausführung aus.
Ein Profil ohne eingerichtete Lesewerkzeuge erhält durch **Nur lesen** allein
keine pauschale Leseberechtigung.

Unter **KI-Zugriff → Erweiterte Berechtigungen** können einzelne MCP-Werkzeuge nach
Prüfung ihrer Bedeutung als lesend freigegeben werden. Der Katalog selbst und seine
`readOnlyHint`-Angaben erteilen keine Rechte. Eine Freigabe bindet Profilrevision,
Werkzeugname und SHA256 des Eingabeschemas. Zum Speichern ist ein erfolgreicher
Katalogtest für die aktuelle Profilrevision nötig. Auch unmittelbar vor dem
Werkzeugaufruf werden Schema und aktuelle Agentenregeln erneut geprüft.

Solche Lesefreigaben funktionieren bei ausgeschalteten Profil-Schreibrechten,
globaler Schreibpause, null erlaubten Änderungen und in reinen Leseläufen. Andere
Werkzeuge bleiben gesperrt. Die allgemeine MCP-Freigabe für sämtliche Werkzeuge
ist davon unabhängig und behandelt nicht einzeln als lesend freigegebene Aufrufe
weiter als mögliche Änderungen. Private Ergebnisse bleiben LOCAL_ONLY und werden
nicht automatisch an Cloudmodelle oder öffentliche Suchdienste weitergegeben.

Für das geprüfte Postfach sind `list_folders`, `list_emails`, `search_emails`,
`read_email`, `get_status`, `daily_digest`, `get_thread` und `list_attachments` die
vorgesehenen Lesewerkzeuge. `save_attachment` und `export_email` erzeugen Dateien
und erhalten keine solche Freigabe.

## Abnahme und offene Punkte

Bridge-Installation und geschützter MCP-Katalogzugriff sind auf der Test-VM geprüft.
Die kompakte Integrationsübersicht und der dreistufige Proton-Assistent sind mit
synthetischen Zugangsdaten im Browser geprüft; 21 gezielte Backend-/Broker-Tests
sind erfolgreich. Release `7c7e8aa` / Schema `0044` ist auf der Test-VM verfügbar;
beide APIs sind gesund. Der echte authentifizierte HTTPS-Status, die ausgelieferte
Einstellungsdatei und der tokengebundene Brokerzugang aus dem App-Container sind
separat geprüft. Bestehende Daten, Rechte, Overlays und unabhängige Netzregeln sind
erhalten; die Live-Prüfung hat keine Mail-Zugangsdaten verändert oder Nachrichten
abgerufen.
Vollständige lokale Suite: 1664 bestanden. Vollständige
[App-CI](https://github.com/sschluet/obdaAI/actions/runs/39165821411): 1658 bestanden,
sechs übersprungen; alle 39 Browserabläufe und drei eingebundene Zusatzprüfungen
sowie Runnersmokes erfolgreich. Die vollständige Browserfolge besteht auch lokal.

Die verschlüsselte Nachab-Sicherung umfasst den Bridge-Anmeldespeicher und den
MCP-/Brokerzustand einschließlich dauerhafter Ausführungsbelege, Dienstdateien,
Zertifikat und eigenem Compose-Overlay. Prüfsummen, Entschlüsselbarkeit und 16
geforderte Archivwurzeln sind am außerhalb der VM gespeicherten Archiv geprüft,
ohne Klartextdateien zu entpacken. Das ersetzt keinen Restoretest; laufende Dienste
und atomare Einzeldateien bilden keine gemeinsame Sicherungstransaktion.

Die persönliche Kontoanmeldung in Bridge und die Eingabe des vorhandenen
Bridge-Zugangs stehen noch aus. Echte Ordner-/Such-/Nachrichtenaufrufe und die
Chat-, Aufgaben- und Projektabnahme bleiben deshalb offen. Der reale Zugriff muss
getrennt von synthetischen UI-/API-Prüfungen bestätigt werden. Keine Nachricht wird
für die Einrichtung verschickt, verschoben oder gelöscht.

Quellen: [Proton IMAP/SMTP](https://proton.me/support/imap-smtp-and-pop3-setup),
[Linux-Installation](https://proton.me/support/installing-bridge-linux-deb-file),
[Signaturprüfung](https://proton.me/support/verifying-bridge-package),
[Bridge CLI](https://proton.me/support/bridge-cli-guide),
[Community-MCP](https://github.com/mhbxyz/protonmail-mcp).
