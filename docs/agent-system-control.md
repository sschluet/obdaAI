# Agentische Systemsteuerung

Anforderung und erste Implementierung vom 18.10.2026. Der neue Agentenlauf ergänzt
die bisherigen festen Schreibdialoge. Synthetische Prüfungen und reale Abnahmen
werden unten getrennt aufgeführt; vollständige Fremdsystemadministration und V1
sind damit noch nicht abgenommen.

## Auftrag

obdaAI soll angebundene Systeme möglichst vollständig aus dem Chat, aus Aufgaben
und innerhalb von Projekten administrieren. Der Benutzer beschreibt ein Ziel;
der Agent ermittelt selbst die Fähigkeiten und den aktuellen Zustand, recherchiert
geeignete Verfahren im Internet, plant, führt erlaubte Schritte aus und prüft das
Ergebnis. Die Integration ist der Zugang zum System, kein festes Aktionsformular.

Das umfasst ausdrücklich Updates und neue Konfigurationen in Home Assistant.
Die Anforderung gilt entsprechend für SSH, Paperless, UniFi und MCP. Nicht jede
Systemfunktion ist über dieselbe Schnittstelle verfügbar. Fehlende Zielrechte,
Transportmöglichkeiten oder Funktionen müssen konkret sichtbar werden; ein
erfolgreicher Verbindungscheck bedeutet keinen vollständigen Verwaltungszugang.

Hermes Agent und OpenClaw sind funktionale Referenzen für Werkzeugschleifen,
Recherche und mehrstufige Ausführung. Es wurde weder die Installation dieser
Plattformen noch eine Übernahme ihrer Berechtigungen beauftragt.

## Ein gemeinsamer Lauf für drei Einstiegspunkte

- **Chat:** Natürlichsprachlicher Auftrag mit sichtbaren Schritten, Rückfragen,
  Freigaben, Ergebnis und Belegen im selben Gespräch. Kein Wechsel in einen
  Integrationsdialog zur manuellen Auswahl jeder einzelnen Aktion.
- **Aufgaben:** Derselbe Agentenlauf, manuell oder terminiert, mit gebundenem
  Auftrag, Zielsystemen, Berechtigungsprofil und Laufzeit-/Kostenlimits. Keine
  Umgehung der Berechtigungen durch einen Scheduler oder n8n.
- **Projekte:** Derselbe Lauf mit explizit gebundenen Integrationen und erlaubtem
  Projektkontext. Projektzugehörigkeit allein erteilt keine Systemrechte und
  keine Erlaubnis, private Unterlagen an einen Cloudanbieter zu übertragen.

Ein Agentenauftrag muss dauerhaft Ziel, Herkunft, ausgewählte Integrationen und
deren Revisionen, Berechtigungsumfang, Limits sowie die Folge der beobachteten
Ergebnisse binden. Modellantworten beschreiben den nächsten Schritt; sie sind
kein eigener Berechtigungsnachweis. Die Ausführung verwendet den gemeinsamen
Aktionsgateway und dessen Prüfung unmittelbar vor dem externen Effekt.

Der Lauf hat die Zustände `queued`, `running`, `awaiting_input`,
`awaiting_approval`, `observed`, `succeeded`, `unverified`, `failed`, `uncertain`
und `cancelled`. Lesen, Recherche, Modellentscheidung, Änderung und Nachprüfung
erscheinen als eigene dauerhafte Schritte; ein Schritt kann `verifying` sein. Ein neues Werkzeugergebnis geht erneut an
den Planer. Eine erzeugte Antwort oder ein HTTP-Erfolg ersetzt die Ergebnisprüfung
nicht. Nach unklarem Effekt darf der Planer keinen vermeintlichen Ersatzauftrag
erzeugen, der dieselbe Änderung erneut auslöst.

## Fähigkeiten und Recherche

Fähigkeiten werden aus der tatsächlichen Installation, ihren Versionen,
zugänglichen API-/MCP-Schemata und den verfügbaren Rechten ermittelt. Feste
Beispielaktionen dürfen das erreichbare Funktionsspektrum nicht definieren.
Die Schnittstellen bleiben austauschbar; der Agent benötigt keine ungeprüft
importierten Erweiterungsprogramme für jedes neue Ziel.

Der gemeinsame Planer erhält unter `interfaces.capabilities` kompakte, von der
Anwendung erstellte Hinweise auf freigegebene Schnittstellen, feste Inspektionen
und geeignete Wege zur Ermittlung weiterer Funktionen. Diese Hinweise ersetzen
keine Zielberechtigungen und begrenzen bestehende Verwaltungsfreigaben nicht auf
eine feste Liste. Modelle müssen Ergebnisse und aktuelle Schnittstellen nutzen;
ein freigegebenes Befehlspräfix belegt allein keinen tatsächlich vorhandenen Befehl.

Vollständige reine Zugriffsfragen werden als lesende Aufträge ohne Recherche,
Modellplanung oder Schreibschritte ausgeführt. Je nach freigegebenem Adapter
stehen HTTP, SSH-Inspektion, MCP-Katalog oder Gmail-Profil zur Verfügung. Für HA
prüft ein authentifiziertes `GET /api/` die erwartete API-Antwort. Bei allgemeinen
HA-Aufträgen steht dieser erste Lesebeleg vor der weiteren Modellplanung bereit;
Recherche bleibt danach bei Bedarf wählbar. Die bereits vorhandenen speziellen
Mail- und Paperless-Leseplaner bleiben erhalten. Andere Formulierungen verwenden
weiterhin den begrenzten allgemeinen Planer. Der
[offizielle HA-REST-Vertrag](https://contributors.home-assistant.io/core/internals/rest-api/)
dokumentiert den Statusendpunkt; dies ist kein vollständiger Administrationsnachweis.
Die zusätzlich als reine Leseoperationen eingeordneten WebSocket-Kommandos
`get_config`, `get_states`, `get_services` und `get_panels` nehmen keine Parameter
an und folgen dem [offiziellen WebSocket-Vertrag](https://contributors.home-assistant.io/core/internals/websocket-api/).

Feste Inspektionen verwenden dieselben dauerhaften Absichten, aktuellen Profil-
und Richtlinienrevisionen, Laufgrenzen und letzten Transportprüfungen wie andere
Werkzeuge. Erfolgreiche oder fehlgeschlagene Schritte werden nicht blind erneut
versandt. Lesefehler enden als `failed` mit festen verständlichen Kategorien
(beispielsweise Anmeldung, Verbindung oder Timeout), ohne Ausnahmetexte oder
Zielinhalte als Fehlermeldung auszugeben. Ungeklärte Änderungen behalten
`uncertain`, auch wenn erst ihre anschließende Nachprüfung unterbrochen wurde.
Bestehende ungeklärte Aufträge werden nicht nachträglich als erfolgreich bewertet.

### Inventar, Folgefragen und begrenzte Lesekorrektur

Eng erkannte Fragen nach den eigenen Lampen verwenden eine feste lesende
`GET /api/states`-Abfrage mit lokalem `light.`-Filter und höchstens 100 Entitäten.
Die Anwendung stellt Namen und beobachtete Zustände direkt dar; eine zusätzliche
Modellplanung ist dafür nicht nötig. Die Zahl beschreibt Entitäten, nicht physische
Geräte. Größere Bestände, unbekannte Zustände und nicht beobachtete Einträge werden
ausdrücklich eingeordnet. Andere Formulierungen und Verwaltungsaufträge bleiben
im allgemeinen Agentenpfad.

„Welche davon sind an?“ nutzt die jüngsten gültigen Lesebelege desselben Gesprächs
und fragt den aktuellen Zustand erneut ab. Nur zuvor dargestellte Entitäten gehören
zur Auswahl; neue Entitäten sowie zuvor ausgeblendete ausgeschaltete Lampen werden
bei weiteren Folgefragen nicht hinzugefügt. Die Quellenbindung wird vor Dispatch
und vor der Antwort erneut geprüft. Die feste Abfrage verwendet denselben dauerhaften
Intent-, Rechte-, Fehler- und Abbruchpfad wie andere Werkzeuge.

Im allgemeinen reinen Leseauftrag wird eine identische bereits erfolgreiche
GET-Abfrage nicht erneut versandt. Der Planer erhält die ursprüngliche Schrittnummer
und kann anhand des Belegs antworten oder eine andere begrenzte Auswahl wählen.
Die vorhandene begrenzte Zahl der Planungskorrekturen verhindert eine Endlosschleife.
Diese Regel betrifft keine Änderungsnachprüfung und keine erneute aktuelle Abfrage
in einem neuen Auftrag.

HA-Fähigkeitshinweise enthalten validierte Beispiele für `/api/states`,
`/api/config` und `/api/services`. Entitätsdomänen sind Filter, keine automatisch
vorhandenen REST-Endpunkte. Lampen verwenden beispielsweise eine lokale
`light.`-Auswahl aus Zuständen; Sensoren können denselben Mechanismus mit ihrem
eigenen Präfix nutzen. Begrenzungen und Trefferzahlen der vorhandenen
HTTP-Projektion bleiben sichtbar. Eindeutige HA-Inventarfragen senken den Auftrag
auf Lesen und null Änderungsschritte. Explizite Verwaltungsaufträge werden dabei
nicht umklassifiziert. Rein lesende Aufträge verlangen keine zusätzliche
Bestätigung; fehlende Fähigkeiten können als nicht vollständig beantwortet enden.

Ein allgemeiner Auftrag darf nach genau einem bestätigten HTTP-GET-404 einen
anderen freigegebenen Leseweg wählen. Der fehlgeschlagene Originalschritt bleibt
erhalten. Derselbe Zielpfad wird nicht erneut versandt; vor einem erfolgreichen
anderen Lesebeleg sind Änderungen, Rückfragen und Erfolgsabschluss gesperrt.
Vorherige Änderungen, ein zweiter Fehler, Authentifizierungsfehler, Timeout und
unterbrochene Ausführungen erlauben diese Korrektur nicht. Die besonderen
Mail-/Paperless-Planer behalten ihre eigenen Quellen- und Fortschrittsverträge.
Nach einer belegten Alternative gelten ausschließlich die bereits vorhandenen
ursprünglichen Rechte und Verifikationspflichten.

Erfolg erfordert neben dem Transportstatus eine gültige Auswahl beziehungsweise
einen erfolgreichen Inspektionsprozess. HTTP-Projektionsfehler und fehlerhafte
SSH-Inspektionen sind keine erfolgreichen Datenabfragen. Das feste SSH-Skript
bricht beim ersten Fehler ab. HA-Webhooks können auch durch GET Automationen
auslösen; sie gelten deshalb als mögliche Änderung und niemals als lesender
Verifikationspfad. Siehe [offizieller Webhook-Vertrag](https://www.home-assistant.io/triggers/webhook/).
Für diese Prüfung werden keine echten Webhooks aufgerufen.

Erfolgreiche native HTTP-, bekannte HA-WebSocket-, SSH- und Gmail-Lesebelege können
wie die vorhandenen Mail-/Paperless-Belege im selben Gespräch gebunden werden.
Deutsche und englische Folgefragen können so ihre Integration behalten.
Profil-, Richtlinien-, Nachrichten- und Belegrevisionen werden erneut geprüft;
Widerruf oder ein fremdes Gespräch erlauben keine Wiederverwendung. Inhalt bleibt
LOCAL_ONLY und innerhalb des bestehenden Kontextbudgets, niemals öffentliche
Recherchegrundlage oder Berechtigungsnachweis.

Gmail-Suchtreffer sind zunächst IDs und belegen keinen Nachrichteninhalt. Für
Zusammenfassungen sind tatsächliche Nachrichten-/Threadabrufe nötig. Ein nativer
Gmail-Abgleich gesendeter Antworten ist derzeit nicht durchgehend implementiert;
entsprechende Statusfragen enden ausdrücklich als nicht belegt. Dies ist keine
Gleichsetzung mit den gesonderten Proton-Kopfzeilen-/Sent-Nachweisen.

Die Integrationsabnahme unterscheidet feste Unit-/API-/Transportverträge,
synthetische Browserdialoge und echte Zielabfragen. Eine erfolgreiche Verbindung
allein ist kein Nachweis erfolgreicher Datenfragen oder Folgefragen. Nicht auf der
Test-VM konfigurierte Dienste erhalten keinen behaupteten Live-Nachweis. Google
Drive ist derzeit Quelle und explizite Dateiablage; ein allgemeines agentisches
Drive-Chatwerkzeug und ein nativer UniFi-Fähigkeitskatalog sind weiterhin offen.

Öffentliche Recherche und private Systembeobachtung sind getrennte Datenwege.
Der lokale Rechercheplan verwendet ein exaktes JSON-Schema mit ausschließlich
`queries`: höchstens drei nichtleere Suchfragen mit je höchstens 500 Zeichen.
Fehlerhafte Felder werden nicht repariert; nachgelagerte Prüfung bleibt bindend.
Recherchefragen dürfen keine Zugangsdaten, internen Adressen, Konfigurationen,
Projektdateien oder alten LOCAL_ONLY-Inhalte aus Werkzeugergebnissen übernehmen.
Der Agent darf solche Inhalte nicht durch die Behauptung „öffentliche Suchfrage“
umklassifizieren. Quellen, Abrufzeit und Versionsbezug werden am Plan festgehalten.
Dokumentation ist untrusted Datenmaterial, niemals eine Erlaubnis zur Ausführung.

Der öffentliche Leser verarbeitet HTML sowie begrenzte Text- und JSON-Quellen
als inerte Dokumentation. URLfreigabe, öffentliche DNS-Pins, kein automatischer
Redirect und Größenlimits gelten für alle Formate. Die Erweiterung ist auf
der Test-VM installiert; bestehende Netzgrenzen bleiben bindend.

Der Agent soll verfügbare Verfahren selbst recherchieren und vergleichen, nicht
den Benutzer zur Recherche oder zum Eintragen jedes API-Payloads auffordern.
Ein neu gefundenes Verfahren muss trotzdem zu einem überprüfbaren Aufruf einer
zugelassenen Schnittstelle werden. Credentials bleiben am lokalen Adapter.

## Home Assistant als vollständiger Abnahmefall

1. Installationstyp, Core-/Supervisor-/OS-Version, Rechte und erreichbare
   Verwaltungswege feststellen. Fehlender Supervisor darf nicht durch einen
   angenommenen Endpunkt oder durch ein simuliertes Update ersetzt werden.
2. Für einen Updateauftrag verfügbare Versionen und passende Versionshinweise
   recherchieren, Auswirkungen einordnen und einen konkreten Ablauf erstellen.
   Zielversion, betroffene Komponenten, Konfigurationsprüfung, Sicherung und
   Wiederherstellungsweg gehören zum Ablauf.
3. Vorhandene Sicherungs- und Wiederherstellungsmöglichkeiten prüfen und deren
   Grenzen offenlegen. Der Benutzer hat am 18.10.2026 ausdrücklich direkte
   Abnahme an seiner HA-Instanz erlaubt, obwohl keine isolierte Instanz und kein
   erfolgreich geprüfter Wiederherstellungsweg vorliegen. Diese Freigabe wird
   als `production_ha_approved` gebunden; sie behauptet keinen Restore-Nachweis.
   Originale und verfügbare Sicherungen vor Änderungen erhalten. Kein destruktiver
   Restore allein zur Abnahme auf der produktiven Instanz.
4. Das freigegebene Update über die zur Installation passende Schnittstelle
   durchführen. Neustarts, zeitweilige Nichterreichbarkeit und asynchrone Jobs
   müssen einen fortsetzbaren Lauf ergeben, keinen blinden Wiederholungsversuch.
5. Tatsächliche Zielversion, Erreichbarkeit und relevante Gesundheitsprüfungen
   kontrollieren. Ein angenommener Updateaufruf allein ist keine erfolgreiche
   Wartung.
6. Für neue Konfigurationen den vorhandenen Bestand lesen, konkrete Änderungen
   vorbereiten, Originale sichern, validieren, anwenden beziehungsweise neu laden
   und die gewünschte Funktion prüfen. Bestehende Nutzerkonfigurationen erhalten;
   bei Fehlern Wiederherstellung anbieten beziehungsweise im erlaubten Umfang
   durchführen und anschließend verifizieren.

Die REST-API für Zustände/Services, WebSocket-Funktionen, Supervisor-Verwaltung
und Konfigurationsdateien sind unterschiedliche Zugriffswege. Ein normaler
HA-Token berechtigt nicht automatisch zu allen diesen Wegen. Reale Abnahme
benötigt einen dafür geeigneten Zielzugang; Produktions-HA ist kein impliziter
destruktiver Restore-Testserver.

## Berechtigungen

Pro System sind Ziel, Kontorechte und gewünschter Autonomieumfang festzuhalten.
Die Auswahl einer Integration darf keine stillschweigende Freigabe zusätzlicher
Systeme, Konten oder Cloudweitergabe bewirken. Widerruf, Pause und Abbruch gelten
auch für schon geplante Folgeschritte. Riskante Eingriffe brauchen eine zum
konkreten Eingriff passende Freigabe oder eine dafür ausdrücklich eingerichtete
Autonomieregel. Agent, manuelle Werkzeuge und Aufgaben verwenden dieselbe Grenze.

Am 18.10.2026 hat der Benutzer modellgenerierte Befehle und Programme auf
freigegebenen SSH-Systemen ausdrücklich auch autonom nach festgelegten Regeln
erlaubt. `shell` bindet diese Erlaubnis an das registrierte Zielkonto und seine
wirklichen Rechte. Ein Arbeitsverzeichnis ist keine Sandbox; eingeschränkte
Zielkonten sind möglich, werden aber nicht durch Modelltext simuliert. Die KI
kann ihre eigenen Agentenregeln weder anlegen noch erweitern.

## Implementierter gemeinsamer Weg

Schema 0044 speichert Agentenregeln und ihre menschlichen Revisionen, Aufträge,
Modellläufe, konkrete Werkzeugabsichten und Ergebnisbelege. Chat und Projektchat
verwenden **Systeme steuern** im Composer; Aufgaben bieten den Schritt
**Agentische Systemsteuerung** mit demselben Worker und denselben Prüfungen.
Rückfragen und einzelne Freigaben unterbrechen den dauerhaften Auftrag. Eine
offene Rückfrage wird nach Neuladen im selben Chat wieder aufgenommen. Ungültige
Modellhüllen und typisierte Werkzeugargumente erhalten höchstens zwei lokale
Format-Rückmeldungen; der Server ergänzt weder Ziele noch Befehle oder Rechte.
Agentenentscheidungen verlangen auch in der Generierungsgrammatik bei jedem
Werkzeug explizite Ziel-ID, Werkzeug und Argumente; die IDs stammen ausschließlich
aus der menschlich gebundenen Auswahl. Der Server ergänzt sie nicht nachträglich. Die native Grammatik bindet außerdem
die vorhandenen typisierten Argumentmodelle und exakt die im Lauf verfügbaren
Werkzeuge. GET kann keinen Schreibkörper oder Wirkungsnachweis enthalten.
Die Grammatik bindet Werkzeug, Zielart, HA-Kommandopräfixe und HTTP-Methoden/Pfade
an die menschlichen Zielregeln. Neue Snapshots enthalten deren gebundene
Schnittstellen; alte Snapshots bleiben mit nachgelagerten Prüfungen kompatibel.
Querystrings und absolute URLs sind im Pfadfeld ausgeschlossen.
Die Prompt-Hülle bleibt kompakt; die vollständigen Argumentregeln werden
ausschließlich als native Ausgabegrammatik übertragen.
Ein konkreter Auftrag enthält bereits den Ausführungswunsch. Die Planeranweisung
verbietet redundante allgemeine Erlaubnisfragen; deren tatsächliche Vermeidung
bleibt Teil der realen Abnahme. Einzelne Freigaben erzwingt der Gateway.
Agentenentscheidungen fordern zusätzlich die feste Decision-JSON-Schemaausgabe am
vorhandenen lokalen Modell an, Recherchepläne ein JSON-Objekt. Diese Anfrageoption
ändert keine Inferenzkonfiguration und erweitert keine Rechte. Die nachgelagerte
Validierung bleibt verbindlich; kein semantisches Reparieren ungültiger Ausgaben.

Der private Planer verwendet ausschließlich das konfigurierte lokale Modell.
Ein begrenzter Verlauf desselben Gesprächs ist lokal an Nachrichtenrevisionen
gebunden. Öffentliche Recherche erhält den aktuellen eingegebenen Auftrag und öffentliche
Quellen, keine privaten Systembeobachtungen oder Rückfragenantworten. Der Planer
kann anhand seiner Beobachtungen weitere Recherchethemen auswählen. Suchfragen,
URLs, Abrufzeit und Ergebnisse bleiben als Belege gebunden. Dokumentation und
Werkzeugausgaben verleihen keine Rechte.

Die Schnittstellen umfassen dynamische REST-Aufrufe innerhalb erlaubter
API-Pfade und Methoden, HA-WebSocket-Kommandos nach freigegebenen Präfixen,
SSH-Befehle und getrennte Prüfskripte mit fester Betriebssystem-/Programmabfrage,
SFTP-Textlesen, MCP-Katalog und Aufrufe
mit aktuellem Schema sowie SMTP an ausdrücklich erlaubte Empfänger. MCP-Schemata
werden im begrenzten Unterprozess vollständig geprüft; externe Schemaauflösung
ist gesperrt. Multipart-Übertragungen können ausschließlich unveränderte,
revisionierte Originale aus dem ausdrücklich gebundenen Projektkontext verwenden.
Es gibt keinen modellgewählten lokalen Dateipfad oder Zielcredential.

DNS-Prüfung, direkte IP-Verbindung, ursprünglicher TLS-Name und fest gebundene
SSH-Hostidentität bleiben erhalten. Öffentliche Integrationsziele benötigen eine
zusätzliche Freigabe für private Daten. Auswahl, Profil, Regeln, Quellen, globale
Schreibpause, Abbruch und Zeitgrenzen werden unmittelbar vor Modellaufruf,
Authentifizierung und Werkzeugübertragung erneut geprüft.

Änderungsabsichten werden vor Versand dauerhaft gespeichert. Unterbrochene oder
unklare Absichten werden nicht automatisch erneut gesendet. Bereits versandte,
unverifizierte Task-Effekte pausieren die Aufgabe auch bei einem Abschluss als
unverified/failed/cancelled vor weiteren Terminen bis zur ausdrücklichen Reaktivierung.
Nur vorbereitete, niemals versandte Absichten lösen diese Pause nicht aus.
Fehlgeschlagene entfernte Skripte stoppen Folgewirkungen; ein nicht erfolgreicher
Exitcode ist kein Beleg dafür, dass zuvor nichts verändert wurde. Ein vor dem Aufruf
festgelegtes GET-Prädikat kann nach Updates oder Antwortverlust begrenzt pollen;
es belegt den beobachteten Zustand, keine Kausalität. Ohne passende Nachprüfung
wird ein HTTP-/MCP-/SMTP-Ack nicht als bewiesene Wirkung ausgegeben. SSH verlangt vor Versand ein separates, vom Agenten definiertes Prüfskript.
Bei einer unpassenden lokalen GET-Projektion bleibt die bereits begrenzte
Originalantwort im fehlgeschlagenen Beleg erhalten, nicht als erfolgreiche
Beobachtung. `projection_error` ist kein Wirkungsnachweis: Weder ein Leseschritt
noch `http.verify` kann damit erfolgreich sein oder eine gültige Lesereferenz liefern.
Es erfolgt keine automatische neue HTTP-Anfrage. Fehler bei Schreibantworten,
Transporten und Antwortgrenzen werden dadurch nicht abgefangen.
Zusätzlich zu den vier oben genannten Zustands-/Konfigurationsabfragen sind die
drei vorhandenen HA-Metadatenabfragen (backup/info sowie GET /info
und /supervisor/info über supervisor/api) sind ausschließlich in ihrer exakten
Form lesend. Andere WebSocket-Aufrufe bleiben mögliche Änderungen; eine
fehlende Lesefähigkeit wird als Beobachtung statt als vermeintlicher Effekt geliefert. Geschlossene SSH-Kanäle
beweisen nicht, dass entfernte Prozesse gestoppt wurden. Der Chat bietet bei
unklarem Ausgang einen neuen, technisch auf Lesen begrenzten Abgleich ohne
Websuche. Das ist keine allgemeine Exactly-once-Garantie für entfernte Systeme.

Bei der Kürzung des privaten Planerkontexts bleiben die neueste Werkzeugbeobachtung
mit begrenzter Status-/Strukturzusammenfassung und die letzte Nutzerrückmeldung
sichtbar. Die Zusammenfassung stammt aus echten Daten, ergänzt keine IDs oder
Sollwerte und erteilt keine Rechte. Vollständige Rohbelege bleiben gespeichert;
ein passender Gesamtkontext wird vor der Übertragung geprüft. Ungültige JSON-Pointer
werden bereits vor einer vorgebundenen Änderung zurückgewiesen.

## Prüfstand dieser Lieferung

- Release fd56e02 / Schema 0044 gesund auf der Test-VM. Vollständige
  [CI39130484648](https://github.com/sschluet/obdaAI/actions/runs/39130484648):1620
  Backend-/PostgreSQLtests bestanden, sechs übersprungen, 41 synthetische
  Browserprüfungen und Container-/Offline-Runnersmokes erfolgreich. 207 gezielte
  lokale Prüfungen, Ruff, mypy und Geheimnisprüfung erfolgreich. App-Sicherungen
  vor/nach der Lieferung verschlüsselt außerhalb der VM hashgeprüft.
- Native lokale SSH-/HA-WebSocket-Testserver und synthetischer Browser prüfen
  Transporte, Fragen/Freigaben, Aufgaben, Widerruf, Antwortverlust und 320px.
  Sie sind von Kontakten zu realen Fremdsystemen getrennt. Öffentliche Bilder
  stammen ausschließlich aus synthetischer Umgebung.
- Native konfigurierte lokale Modellantworten erfüllen die neue zielgebundene
  Grammatik für HA-Backupmetadaten und Paperless-GET, ohne Werkzeugdispatch.
- Reales SSH auf efbd4ed: Chat legt eigene Datei an und prüft sie; unabhängiges
  SFTP bestätigt Inhalt/Hash. Eine echte Aufgabe entfernt sie hashgebunden,
  separat geprüft. Die Aufgabe brauchte eine klärende Rückmeldung.
- HA-Lesechat auf fd56e02: HTTP200 und observed, ohne Formatkorrektur oder
  menschliche Fortsetzung.
- Paperless auf fd56e02: öffentliche Recherche und drei echte GET-Schritte,
  wiederholt ungeeignete Auswahl und schließlich Anbieterzeitgrenze; kein Effekt.
  HA-Projekt: öffentliche Recherche, wiederholte GET404 auf gewähltem Pfad,
  eigener Prüflauf ohne Effekt beendet. Unabhängig kein eigener Tag und keine
  eigene HA-Testautomation in Konfiguration oder Laufzeit. 17 eigene Prüfläufe
  privat auditgesichert; keine echten Nutzerinhalte veröffentlicht.
- Vollständige öffentliche Dokumentationsabrufe sind durch bestehende Netzgrenzen
  eingeschränkt. Ein konkreter begrenzter Netzwerkentwurf und die Erhöhung des
  Anbieterzeitlimits sind separat angefragt, nicht angewendet. Eigene Testobjekte
  bleiben bis zur ausdrücklichen Löschfreigabe erhalten. Inferenzwerte unverändert.

## Offene Abnahme

- Die korrigierten API-Läufe führen Verwaltungseffekte und unabhängige Prüfungen
  ohne manuell nachgereichte Schnittstellendetails aus.
- Projektvererbung und autonome Aufgaben bewähren sich auch bei umfangreicheren
  tatsächlichen Verwaltungszielen; redundante Rückfragen und fehlerhafte
  Modellannahmen sind weiterhin beobachtete Grenzen.
- HA-Update und neue HA-Konfiguration werden einschließlich Sicherung,
  Validierung, Ausführung und Nachprüfung an der freigegebenen Instanz abgenommen.
- Paperless-, UniFi- und MCP-Verwaltung werden je tatsächlich konfiguriertem Ziel
  getrennt live nachgewiesen. SMTP-Akzeptanz bleibt von Zustellung unterschieden.
- Öffentliche Recherche liefert konkrete passende Verfahrensbelege innerhalb
  erlaubter Netzgrenzen. Private Beobachtungen verlassen weder Such- noch
  Modellgrenzen; manipulierte Texte erweitern keine Rechte.
- Worker-Abbruch, Timeout während einer Änderung, Widerruf und offene Freigaben
  sind synthetisch geprüft; entsprechende reale Störfallabnahmen bleiben offen.

Die bisherigen festen Formulare und synthetische Agentenabläufe ersetzen diese
Abnahme nicht. Ein funktionsfähiger Transport oder Verbindungscheck beweist keinen
vollständigen administrativen Zugriff und keine hinreichende Planungsqualität.

## Geprüfte Primärquellen

Am 18.10.2026 zur Einordnung gelesen; externe Dokumentation ist kein Produkt-
oder Laufzeitnachweis für obdaAI:

- [Hermes: Tools & Toolsets](https://hermes-agent.nousresearch.com/docs/user-guide/features/tools)
- [Hermes: Skills System](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/)
- [OpenClaw: Exec approvals](https://docs.openclaw.ai/tools/exec-approvals)
- [Home Assistant: REST API](https://contributors.home-assistant.io/core/internals/rest-api/)
- [Home Assistant: WebSocket API](https://contributors.home-assistant.io/core/internals/websocket-api/)
- [Home Assistant: Supervisor API](https://contributors.home-assistant.io/apps/supervisor-api/)
- [Home Assistant: Update](https://www.home-assistant.io/integrations/update/)


## Zielbezogene Planung und Kontextgrenzen (24.11.2026)

Die gemeinsame Administrationsplanung setzt die Anweisung aus einem unveränderlichen
Sicherheitskern und Hinweisen ausschließlich zu den tatsächlich gebundenen Zieltypen
zusammen (`agent_instructions.py`). Werkzeugschemas und Regeln werden nicht gekürzt
oder durch Modellannahmen ersetzt. Die feste lokale Projektwahl beziehungsweise der
aktuelle lokale Standard bestimmt bereits vor der Kontextkompression das Budget;
eine größere globale Einstellung darf eine kleinere Anbietergrenze nicht übergehen.
Die abschließenden Anbieter- und Berechtigungsprüfungen bleiben zusätzlich wirksam.

Große Belegnutzlasten werden in der abgeleiteten Modellsicht ausdrücklich mit Hash
und Auslassungsmarker dargestellt. Ältere, ausdrücklich verifizierte abgeschlossene
Änderungen können als einzelne Einträge in `effect_ledger` erscheinen: Sequenz,
Status, Ziel-/Prüfverknüpfungen, Prüfflags und Originalhashes bleiben erhalten.
Ungeklärte Änderungen werden niemals als verifiziert zusammengefasst; ihre
Kontrollfelder bleiben erhalten. Originalbelege in der Datenbank bleiben unverändert.
Ein Kontextfehler startet keinen Ersatzaufruf und wiederholt keine Änderung.

Objektantworten erhalten zusätzlich eine begrenzte strukturierte Sicht tatsächlich
vorhandener Skalarwerte. Version und Zustand bleiben auch hinter großen Listen
sichtbar; ausgelassene Container werden ausdrücklich gezählt. Bei Update-Entitäten
bleiben beobachtete installierte/neue Version und Fortschritts-/Funktionswerte auch
in projizierten Zeilen erhalten. `step_status` bezeichnet den ursprünglichen
Werkzeugstatus, `model_view_only` die abgeleitete Anzeige: eine gekürzte Modellsicht
bedeutet keine teilweise Ausführung und benötigt keine erneute Lesebestätigung.

Die Regression umfasst einen HA-Auftrag mit großer Aktionsliste, Sicherung,
mehreren Updates und Nachzustandsprüfung sowie einen unsicheren Updateausgang.
Dabei sind Modell und HA-Ziel simuliert; dies ist keine reale HA-Updateabnahme.
Ein vorhandener gescheiterter Auftrag wird zur Diagnose ausschließlich lesend
rekonstruiert und niemals automatisch fortgesetzt.
