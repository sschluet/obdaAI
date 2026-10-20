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
ausgeschaltet; die Grenze für Änderungen beträgt null. Aktivierte Verbindungen stehen danach im neuen Chat automatisch bereit.
Eine Mailfrage startet die passenden freigegebenen Werkzeuge; eine manuelle
Einzelauswahl ist optional. Bestehende explizite Ausschlüsse bleiben wirksam.

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

## Verbindungstest nach erfolgreicher Bridge-Anmeldung

Bei der Einrichtung wird das bisherige Profil zunächst gesperrt. Der feste
Postfachadapter bleibt für höchstens 120 Sekunden ausschließlich zur Prüfung
erreichbar. Diese Ausnahme bindet Betreiberprofil, Adresse und die aktuelle
Einrichtungsrevision; sie erteilt keine Lesewerkzeuge oder Schreibrechte.
Nach erfolgreicher Zugangskonfiguration darf die Katalogprüfung kurz auf die
Netzaktualisierung warten. Die Zugangskonfiguration wird dabei nicht wiederholt.
Ein abgebrochener oder abgelaufener Versuch bleibt gesperrt und benötigt eine
bewusste neue Einrichtung oder eine geprüfte Wiederaufnahme durch den Betreiber.

Wurde Bridge für die Anmeldung mit `--cli` gestartet, beende diese Konsole nach
`info` mit `exit`, damit der eingerichtete Hintergrunddienst wieder starten kann.
Die ausgegebenen Zugangsdaten gehören ausschließlich in den Einrichtungsdialog.

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

## Betrieb des festgeschriebenen Community-MCP

Die installierte Version 0.4.0 benötigt eine private Laufzeitkorrektur für das
bereits gepinnte Bridge-Zertifikat: Ihr selbst erzeugter `SSLContext` lädt die
Zertifikatsdatei ausdrücklich mit `load_verify_locations`. Die Umgebungsvariable
`SSL_CERT_FILE` allein genügt bei diesem Kontext nicht. Hostnamenprüfung und
`CERT_REQUIRED` bleiben eingeschaltet; es wird kein globaler Zertifikatsspeicher
geändert. Original, Prüfsummen und Rückweg werden außerhalb von Git erhalten.
Der Dienst ist damit lokal angepasst und kein unverändertes Upstream-Paket.

Der Dienst bündelt nackte Listen der freigegebenen Werkzeuge `list_folders`,
`get_status`, `get_thread` und `list_attachments` jeweils als einen JSON-Textblock,
ohne Kürzung oder Schemaänderung. Die App-Grenzen bleiben unverändert. Diese
private Kompatibilitätskorrektur verhindert, dass das SDK pro Eintrag einen
separaten Antwortblock erzeugt oder leere Listen ohne Textblock zurückgibt.
Vollständige, leere und übergroße Listen sind synthetisch geprüft. `list_emails`,
`search_emails` und `daily_digest` liefern bereits umschlossene Objekte und
benötigen diese Anpassung nicht. Die Erweiterung ist privat auf der VM angewandt;
sie ist kein Nachweis tatsächlicher Nachrichten-, Thread- oder Anhangabrufe.

## Mehrstufige Mailfragen und Fehlerbehandlung

Release a1edf85 korrigiert die Bestätigungsschleife für unterstützte einfache
Heute-/Wochenübersichten. Die genaue Frage „Was gab es heute für neue Mails?“ ist
in einem frischen authentifizierten Chat tatsächlich abgenommen: automatisches
Proton-Profil, aktueller Katalog, genau eine Nachrichtensuche, belegte Antwort und
Abschluss `observed`, ohne Rückfrage, Nutzereingabe oder Modellaufruf.
Tagesgrenzen, Antwortbelege und sichtbare Umfangsgrenzen sind auf der VM geprüft;
private Mailwerte und Nachrichtenzahlen wurden nicht exportiert.

Vorhandene Lesefreigaben, bekannte Kalendergrenzen und beobachtete Standardordner
benötigen keine erneute Bestätigung. Explizite Filter, Ordner-/Kontowünsche,
bestehender Kontext und tatsächlich notwendige fehlende Angaben bleiben erhalten.
Alte wartende Nutzeraufträge werden nicht automatisch fortgesetzt, abgebrochen
oder in eine Standardabfrage umgedeutet. Für die neue Tagesabnahme wurde ein neuer
Chat verwendet; bestehende Rückfrageschleifen sind kein erneut ausgeführter Test.
Lokal 1953 Tests und vollständige [CI39451467433](https://github.com/sschluet/obdaAI/actions/runs/39451467433) mit 1947
bestandenen und 6 übersprungenen Tests sind erfolgreich. Der nachfolgende
Wochenbeleg dokumentiert die vorherige, getrennte Abnahme.

Release b59b6e6 ist vollständig geprüft und auf der Test-VM installiert. Eine
frische echte Wochenübersicht ist über den normalen authentifizierten Chat-Weg
abgenommen: automatische Proton-Auswahl, aktueller Katalog, tatsächliche Suche,
belegte lokale Übersicht und Abschluss `observed`. Kontoanmeldung, manuelle
Auswahl oder Ordner-/Filterrückfrage sind dafür nicht nötig. Die Qualitätsprüfung
bleibt auf der VM; reale Mailtexte und Nachrichtenzahlen werden nicht exportiert.

Die unterstützte einfache Heute-/Wochenfrage ohne bestehenden Kontext verwendet einen engen
Anwendungsplan aus tatsächlich beobachteten, ausdrücklich lesend freigegebenen
Schemas. Konto, aktuelle Ziel-/Policyrevisionen und eingefrorener Kalender bleiben
gebunden. Ein dauerhafter Lese-Intent wird vor dem normalen gemeinsamen Dispatch
festgehalten; Widerruf, Abbruch und unklare Ausgänge behalten ihre Sperren.
Unbekannte Schemas werden nicht geraten. Ein Modellaufruf ist hierfür nicht nötig;
die Modellkontextgrenze ist bei diesem Lauf ausdrücklich nicht anwendbar.

### Betreiberkonfiguration für API und Worker

Der ausführende Agent-Worker benötigt dieselben zwei Betreiber-Pins wie die APIs.
Ergänze im geprüften privaten Compose-Overlay unter `services.worker.environment`
die bereits für `api` und `api_https` gesetzten Werte:

- `HUB_PROTON_BRIDGE_INTEGRATION_ID`: identische ID des vorhandenen freigegebenen Profils.
- `HUB_PROTON_BRIDGE_MCP_URL`: identische bereits zugelassene MCP-Adresse.

Keine neue ID und kein neues Ziel erzeugen. `HUB_PROTON_BRIDGE_CONTROL_URL` und
`HUB_PROTON_BRIDGE_CONTROL_TOKEN_FILE` bleiben ausschließlich bei den APIs;
Control-Token und sonstige Zugangsdaten nicht an den Worker weiterreichen.
Original-Overlay sichern und ausschließlich diese zwei nicht geheimen Werte
weitergeben. Nach Prüfung der effektiven Compose-Konfiguration den betroffenen
Worker im autorisierten Deployment mit demselben Anwendungsimage neu erstellen
und seine Gesundheit prüfen. Vergleiche anschließend die tatsächlich geladenen
Settings in beiden APIs und im Worker auf Gleichheit, ohne Werte oder Secrets zu
protokollieren. Eine Prüfung allein im API-Container genügt nicht. Erst danach
eine frische authentifizierte Übersicht als eigenen Prüflauf starten; alte oder
unklare Intents nicht wiederholen und keine Nutzeraufträge abbrechen.

Der erste eigene Wochenprüflauf mit Image b59b6e6 hatte wegen fehlender Pins im
Worker nur den Katalog gelesen und eine unnötige Ordner-/Filterrückfrage gestellt.
Diese Abnahme war nicht erfolgreich; ausschließlich dieser eigene wartende Lauf
wurde kontrolliert abgebrochen. Nach gezielter Konfigurationsweitergabe ohne
Änderung von Anwendungscode, Kontorechten oder Geheimnissen wurde die neue echte
Wochenabnahme erfolgreich durchgeführt. Originale und unabhängige Konfiguration
bleiben erhalten; das private Overlay wird ausdrücklich nicht als unverändert
beschrieben.

### Belegte Anzeige und verbleibende Grenzen

Nach wirklichem Abruf entstehen höchstens 20 Kopfzeilen aus den Originalbelegen,
mit Konto, Ordnerumfang und sichtbaren Grenzen. Aware Datumswerte werden lokal
gefiltert; bei fehlender Empfangszeitzone wird ein ersatzweise verwendetes
Header-Datum gekennzeichnet. Unzuordenbare Nachrichten stehen getrennt. Die
Übersicht behauptet weder Vollständigkeit noch eine verifizierte Empfangszeit.
Der grobe Vorfilter beginnt am Vortag der Kalendergrenze: IMAP-SINCE vergleicht
Kalenderdaten ohne Zeit und Zeitzone ([RFC3501](https://www.rfc-editor.org/rfc/rfc3501.html)).
Die eingefrorenen Grenzen einschließlich Sommerzeitwechsel bleiben maßgeblich.

Bestehender Gesprächs-/Projektkontext, mehrere Konten, Gmail und komplexe Fragen
nutzen weiter den lokalen Modellplaner. Dessen strukturierte, geschützte
Nachrichtensicht bewahrt relevante Kopfzeilen und Ergebnisgrenzen trotz Kürzung;
Originalbelege und vollständige Werkzeugschemas bleiben erhalten. Acht vollständige
Schemas mit großen Status-/Suchergebnissen bestehen die unveränderte 14-kB-Grenze.
Es gibt keinen Cloudfallback, keine zusätzlichen Rechte und keinen blinden Replay.

Lokale Planungsfehler nennen den wirklichen Fehlertyp. Der Composer wird nach
Fehlern und nachgelagerten Ladefehlern wieder benutzbar; aktive Aufträge behalten
ihre Sperre. „Frage erneut vorbereiten“ kopiert die ursprüngliche Frage, ohne sie
automatisch zu senden oder einen alten Intent erneut auszuführen.

Lokal **1902 Tests** erfolgreich; vollständige [CI39410505466](https://github.com/sschluet/obdaAI/actions/runs/39410505466):
**1896 bestanden, 6 übersprungen**, Browser- und Runner-Prüfungen erfolgreich.
Echte Wochenabnahme und synthetische Tests sind getrennte Nachweise. Frühere
Timeout-, Vorbereitungsschleifen-, Leermeldungs- und Rückfrageläufe zählen nicht
als erfolgreiche Mailabnahme. Nachrichtentexte, Threads, Anhangmetadaten sowie
reale Aufgaben-/Projekt- und Gmail-Läufe bleiben gesondert offen.

## Abnahme und offene Punkte — vorheriger Stand

Release **81e9c3a / Schema 0045** ist auf der Test-VM installiert; beide APIs sind
gesund. Bridge-Anmeldung, gepinntes STARTTLS, Katalogprüfung und authentifizierte
HTTPS-Einrichtung sind erfolgreich. Die vorhandenen Zugangsdaten und ausdrücklichen
Lesefreigaben bleiben erhalten; allgemeiner MCP-Vollzugriff, autonome Änderungen,
Versand und Postfachänderungen bleiben gesperrt.

Die Frage **„Welche neuen Mails gab es heute?“** ist in einem frischen Chat mit
automatisch verfügbaren Verbindungen erfolgreich abgenommen: Zuordnung zum
vorhandenen Proton-Profil, Katalog, tatsächlicher schema-/richtliniengebundener
`list_emails`-Aufruf und eine abgeschlossene lokale Antwort. Keine manuelle Auswahl,
zusätzliche Rückmeldung oder Webrecherche war nötig. Private Ergebnisse bleiben
`LOCAL_ONLY` und wurden nicht in Prüfbelege oder öffentliche Dateien exportiert.

Die reine Mailplanung verwendet einen kompakten eigenen Leitfaden und vollständige
beobachtete Schemas, ohne doppelte Katalogdarstellung. Originalbelege bleiben
unverändert. Der Katalog allein gilt nicht als erfolgreicher Postfachabruf.
Anbieterzeitlimits, Kontext-/Ausgabegrenzen und Rechte wurden nicht erhöht.
Die isolierte Schema-Prüfung behält ihre vorhandenen CPU-/Wandzeit-/Speichergrenzen.

Lokal bestehen **1859 Tests**, Ruff, mypy und Geheimnisprüfung. Vollständige
[App-CI39311706155](https://github.com/sschluet/obdaAI/actions/runs/39311706155):
**1853 bestanden, sechs übersprungen**; alle sechs Pflichtjobs einschließlich
39 synthetischer Browserabläufe, drei eingebundener Zusatzprüfungen und Runnersmokes
erfolgreich. Synthetische Browserprüfungen und echter Mail-Chat sind getrennte Belege.

MCP-Zeitfilter beziehen sich auf das Serverdatum. Zum Beispiel umfasst
`daily_digest(days=1)` grundsätzlich auch gestern und hat keine obere Tagesgrenze.
Für „heute“ müssen die zurückgegebenen Datumswerte gegen den eingefrorenen
Kalenderkontext geprüft werden. `total_recent` zählt die zurückgegebenen Nachrichten,
keinen garantiert vollständigen Tag; Listenlimits sind bei der Antwort zu beachten.

Einzelabruf vollständiger Nachrichtentexte, Threads und Anhangmetadaten sowie
reale Mail-Aufgaben-/Projektläufe sind noch nicht gesondert abgenommen. Anhang-
downloads, Dateiexport, Versand und Postfachänderungen sind nicht freigegeben.

Die frühere vollständige verschlüsselte Kopie außerhalb der VM ist per
Entschlüsselung, Prüfsummen und allen 16 Proton-Archivwurzeln bestätigt. Vor dem
aktuellen Codewechsel wurde zusätzlich der Datenbank-/Konfigurationszustand auf
der VM verschlüsselt gesichert. Pipeline und Chiffretext-Prüfsummen sind geprüft,
Entschlüsselung dieser Teilkopie und Restore nicht. Es ist keine neue vollständige
Systemkopie. Bridge, vorhandene Backups, Berechtigungen, Overlays und unabhängige
Netzregeln bleiben erhalten; Reserve und Quote wurden nicht geändert.

Quellen: [Proton IMAP/SMTP](https://proton.me/support/imap-smtp-and-pop3-setup),
[Linux-Installation](https://proton.me/support/installing-bridge-linux-deb-file),
[Signaturprüfung](https://proton.me/support/verifying-bridge-package),
[Bridge CLI](https://proton.me/support/bridge-cli-guide),
[Community-MCP](https://github.com/mhbxyz/protonmail-mcp).

**Frage erneut vorbereiten** übernimmt nach einem fehlgeschlagenen Auftrag nur
die ursprüngliche Frage in den Composer. Erst erneutes Senden startet einen neuen
Auftrag mit aktuellen Profilen und Freigaben; frühere Werkzeugschritte werden
nicht automatisch wiederholt.

## Folgefragen und Antwortmerkmale

Der neue Entwicklungsstand erhält kontogebundene Nachrichtenreferenzen aus echten
Abrufen für Folgefragen. Ein Katalogabruf allein erlaubt keinen erfolgreichen
Abschluss. Der geprüfte Metadatenpatch ergänzt vom Server gelieferte Antwortflags
sowie In-Reply-To und References. Ein Antwortflag bedeutet „als beantwortet
markiert“. Eine Antwortbeziehung benötigt passende Nachrichtenkennungen und einen
beobachteten Gesendet-Ordner desselben Kontos; ähnliche Betreffzeilen genügen nicht.
Ohne hinreichende Belege bleibt der Antwortstatus unbekannt. Versand und tatsächliche
Zustellung werden damit nicht bewiesen. Installation und reale Folgeabnahme dieser
Erweiterung stehen noch aus; vorhandene Lesefreigaben bleiben unverändert.
