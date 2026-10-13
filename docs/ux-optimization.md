# Integrierter Arbeitsraum — lokale Lieferung vom 07.10.2026

Der Nutzer hat die Umsetzung des Optimierungsplans zunächst ausschließlich lokal
mit GitHub-/Website-Abgleich beauftragt. Der Testserver ist nicht erreichbar und
wurde weder angesprochen noch verändert. Keine produktive Migration oder Live-
Modellabnahme aus den lokalen Fixturetests ableiten.

## Geliefert

- Chat mit optionalem Arbeitsbereich für Dateien, Quellen, Antwortvorgaben und
  Aufgaben. Desktop nebeneinander, mobile Ansicht über eigene Tabs/Schließen.
- Explizite Chatantwort als Datei und eigene Nachricht als Aufgabenentwurf ohne
  Verlassen des Gesprächs. Ausgangsprojekt und Herkunft bleiben gebunden.
- Quellen im Projektchat lokal hochladen; verarbeitete Quellen und tatsächlich
  verwendete Antwortfundstellen sind unterschiedlich bezeichnet.
- URL-Navigation erhält Gespräch/Projekt/Ansicht und unterstützt Zurück/Neuladen.
  URL enthält nur Objekt-IDs und Ansichtsparameter, keine Texte oder Secrets.
- Ungesendete Chattexte bleiben im aktuellen Browser-Tab erhalten. Gesprächswechsel
  stellt sie synchron wieder her; während des Wechsels ist die Eingabe gesperrt.
- Dateidialog: KI-Entwurf oder direkte Inhaltseingabe; Wechsel erhält Ziel/Inhalt.
  Abschnitt-/Tabellen-/Bilddetails sind optional. Vorschaupflicht und alte Versionen
  bleiben erhalten. Wiederaufnahme speichert keine Modelltokens/Freigaben und
  blockiert bei Quellen-, Chat- oder Versionsdrift bis erneuter Planung bzw.
  ausdrücklicher manueller Kopie ohne frühere Herkunft.
- Aufgaben: Name/Ziel/Termin zuerst, Zusammenfassung mit Änderungsaktionen,
  Quellen und Ablaufdetails optional. Schreibaktionen bleiben sichtbar. Neue
  Aufgaben sind nach Speichern pausiert. Unbenutzte Taskeditoren erzeugen keine
  Entwürfe. Wiederaufnahme neuer Entwürfe verlangt aktuelle Bindungsprüfung;
  veraltete Quellen/Skills/Ziele benötigen ausdrückliche Aktualisierung/Entfernung.
- Antwortvorgaben: Sprache, Länge, Ton, Gliederung. Persönlich → Projekt → Gespräch,
  mit sichtbarer Herkunft, serverseitigen unveränderlichen Revisionen und Reset.
  Jeder neue Chatlauf bindet einen eingefrorenen Snapshot samt Hash; laufende
  Antworten behalten ihre Vorgaben. Der tatsächlich antwortende Provider erhält
  feste Stilvorgaben erst nach dem Routing. Ein angepasster Stil benötigt deshalb
  ggf. einen zusätzlichen Antwortmodellaufruf statt der kurzen Routerantwort.
- Migration 0025 ist additiv. Downgrade mit vorhandenen Einstellungen/Revisionen
  wird verweigert. Globale/Projekt-/Gesprächsvorgaben erteilen keine Cloud-, Web-,
  Modell-, Netzwerk- oder Schreibrechte. Keine freien Promptparameter eingeführt.
- Logout löscht alle privaten UI-Entwürfe unter dem gemeinsamen Sessionpräfix.

## Prüfung

Ruff, Mypy (63 Module), Frontend-Typecheck/Build und Source-Scan bestanden.
Die komplette lokale Python-Suite: 577 bestanden, 13 PostgreSQL-Fälle ausgelassen; GitHub-CI prüft diese mit ihrer eigenen
temporären Datenbank. Neue Tests decken CAS, Vererbung/Reset, eingefrorene Läufe,
Cloudgrenzen, migrationssicheren Datenerhalt und konkurrierende PG-Erstschreibungen ab.

Browserchecks: allgemeine App, Dateien, native Anbieter, Projekträume, Pipeline,
integrierter Arbeitsraum, Aufgaben-UX und Antwortvorgaben. Diese verwenden nur
synthetische Daten und Anbieter. Datei-/Taskentwürfe werden über Reload und Drift
geprüft, Layouts separat Desktop/Mobil. Keine allgemeine Fakten-, Server-, Geräte-
oder Wiederherstellungsabnahme behaupten.

Finale GitHub-CI: b41b269 / Lauf 37602855825, sechs Jobs erfolgreich, 590 Tests
einschließlich temporärem PostgreSQL und alle acht Browserprüfungen bestanden.
Die Testanmeldung respektiert die unveränderte App-Sperrfrist. Ein gezielter
Test bestätigt den erfolgreichen CSRF-Wert nach einer abgewiesenen Anmeldung.

## Noch offen aus dem Gesamtplan

- Umfangreichere Startübersicht und zusätzliche Suchtypen (z. B. Skills/Werkzeuge)
  sowie Dokumentvolltexte. Die sechs Kernobjekttypen sind nun über die
  durchgehende Arbeitsraumsuche abgedeckt.
- Vollständige Vorlagenbibliothek und direktes visuelles Bearbeiten aller nativen
  Officeformate, selektive Text-KI-Änderungen sowie Versionsvergleich.
- Zusätzliche Dateilayout-/Antwortprofile, unabhängige Vorgaben pro Einzelauftrag,
  konkrete Modellpräferenzen und geordnetes Benachrichtigungsverhalten.
- Wiedereinstieg in ungespeicherte Änderungen bestehender Aufgaben; neue Entwürfe
  sind bereits abgedeckt. Browser-Tab-Speicherung ist keine serverseitige Entwurfs-
  synchronisierung zwischen Geräten.
- Breiter Fakten-/Layoutkorpus, echte Safari-/iPhone-Geräte, längere Last und
  erneute reale lokale Inference-/Serverabnahme nach wiederhergestelltem Zugang.
- Die bisherigen offenen V1-Grenzen bleiben bestehen. Interaktiver Browser,
  weitergehende Aktionen/Graphen und externe HA-/n8n-Recovery sind keine Teile
  dieser Bedienlieferung.

GitHub und die öffentliche Projektwebsite werden gemeinsam gepflegt. Die neuen
Bedienfunktionen sind dort als lokal geprüft markiert; bestehende Live-Belege
bleiben an den früher getesteten Anwendungscode gebunden.

## Test-VM-Rollout am 09.10.2026

Der Nutzer hat die bestehende Test-VM wieder freigegeben und verlangt die
Installation jeder geprüften Weiterentwicklung. Installiert ist aea1ecc auf Schema
0025. Alle neun eigenen App-/Runnercontainer tragen diesen Release; die bestehende
Datenbank blieb bestehen. Beide APIs gesund, IPv4-/IPv6-Regeln semantisch identisch
(Zeitstempel und Paketzähler aus dem Vergleich ausgeschlossen), bestehende
Compose-Overlays, Secrets und fremde Dienste erhalten. Verschlüsselte Sicherung
vor Installation wurde off-VM kopiert und per Hash geprüft.

Echte lokale Modellprüfung mit eigenem Testprojekt: scoped Antwortvorgaben und
englische kurze Ausgabe sowie Inventarwerte sieben/blau bestanden. Der erste
Versuch mit einer ausdrücklich als synthetisch bezeichneten Quelle wurde vom
Modell inhaltlich abgelehnt und bleibt als Fehlbeleg erhalten. Dies ist keine breite
Faktenabnahme. Nur eigene QA-Projekte/Chats archiviert, Originale erhalten.
HTTPS/Auth/CSRF/Origin/Logout bestanden; globale Antwortvorgaben unverändert.

Frische verschlüsselte Off-VM-Sicherung und isolierter Restore: Schema0025,
57 Originalhashes, 34 Artefaktversionsdatensätze, zwei Einstellungsrevisionen sowie
Schlüssel und Overlays vorhanden. Temporäre Datenbank entfernt. Keine produktive
Datenbankwiederherstellung oder HA-/n8n-Writes. Belege unter .local/deployment/.

## Nächster lokaler Baustein: Dateivorlagen

Word Projektübersicht/Besprechungsnotiz/Entscheidungsvorlage und PowerPoint
Projektstatus mit vier Folien sind als leere, direkt bearbeitbare Gliederungen
umgesetzt. Auswahl überschreibt keine Inhalte. Vorhandene Entwürfe verlangen
eine ausdrückliche Ersetzungsbestätigung; alte gespeicherte Versionen bleiben
erhalten. Ein eigener Button übernimmt einen tatsächlich wirksamen Vorlagenauftrag
in die lokale Modellplanung, ohne Aussagen zu erfinden oder Freigaben zu erteilen.
Lokaler Browsercheck für Prompt, Tokeninvalidierung, Ersetzungsentscheidung, native
Vorschau, Versionen, Reload und mobile Darstellung bestanden.

GitHub-Zugang ist am 09.10.2026 mit HTTP401 ungültig. Vorlagen-CI, Veröffentlichung
der neuen Website und der folgende Vorlagen-Rollout warten auf Wiederanmeldung.
Der bereits geprüfte Bedienstand ist davon unabhängig auf der Test-VM installiert.

## Designmodernisierung vom 09.10.2026

Neue gemeinsame Design-Tokens für warme helle Flächen, dunkle grüne Navigation,
Jade-Akzente, klare Systemtypografie und editoriale Startansicht. Karten, Eingaben,
Quellen-/Statuschips, Chat, Arbeitsbereich und Datei-/Aufgabendialoge teilen eine
ruhige Hierarchie. Hell-/Dunkelmodus und bewegungsreduzierte mobile Navigation
werden getrennt geprüft. Keine externen Fonts/Tracker oder neue Abhängigkeiten.
Keine Änderungen an Backend- oder Freigabeverträgen.

Der eigene Browsercheck prüft tatsächlich angewandte Farbtokens, 320–1440px ohne
horizontalen Overflow, den geschlossenen mobilen Drawer bei reduzierter Bewegung
und erhaltene Inhalte beim Wechsel zwischen KI-/manueller Dateibearbeitung.
Öffentliche Screenshots enthalten ausschließlich eigene synthetische Beispiele.

Design-Rollout geprüft: 8989b26 / Schema0025, CI37914965230 sechs Jobs grün mit
590 Tests und zehn Browserchecks. Der mobile Quellenkonfigurationsdialog bleibt
intern scrollbar, Abbrechen erreichbar. Test-VM liefert die neuen CSS-Tokens über
gepinntes HTTPS aus; bestehende DB, Overlays, Secrets und Netzregeln bewahrt.
Verschlüsselte Sicherung off-VM verifiziert, Rückweg zum vorherigen Image erhalten.
Die bereits geprüften Dateivorlagen sind mit diesem Release installiert.


## 09.10.2026: Interaktion nach Nutzerfeedback

Die erste Designrunde ließ native Auswahllisten im Composer zurück. Diese
Lieferung modernisiert die Bedienung selbst: kompakte Plus-Aktionen, erklärtes
Modellmenü, expliziter Webknopf und kontextgebundene Projektquellen. Vier doppelte
Kopfaktionen werden durch einen Arbeitsbereich-Zugang und Antwortstil ersetzt.
Antwortvorgaben, Dateiformate und Vorlagen werden direkt über Radiokarten statt
Selects gewählt. Projekt- und Arbeitsbereichuploads teilen eine moderne lokale
Ablagefläche mit Dateiauswahl und Drag-and-drop.
Mitwachsendes Eingabefeld, Shift-Enter/IME, Menü-Fokus, Escape/Pfeiltasten und
kurze mobile Viewports sind gezielt geprüft. Bestehende Daten-/Freigabegrenzen
und Schema0025 bleiben erhalten. Native Listen in komplexen Verwaltungsformularen
sind noch vorhanden; diese Lieferung behauptet keine vollständige UX-Neugestaltung
aller Werkzeuge oder echte Safari-/Geräteabnahme.


Abnahme dieser Interaktionsrunde: Release854e587 / Schema0025, CI37921380828
mit sechs erfolgreichen Jobs, 590 Tests und elf Browserprüfungen. Eigene Test-VM
installiert; gepinnte HTTPS-Assets und gezielter Live-Browsercheck (keine neuen
Nachrichten oder Einstellungswrites) bestätigt. Backup/Off-VM-Hashes, Rollback,
DB, acht Overlays und unveränderte Netzwerkregeln geprüft. Neue öffentliche
Screenshots stammen ausschließlich aus der getrennten synthetischen Demo.


## 10.10.2026: Verarbeitung direkt an der Antwort

Kleiner Fuß je Assistentenantwort nennt den tatsächlich gespeicherten Anbieter
und die Modellkennung des Modellaufrufs. Message.run_id verbindet die Antwort
mit ihrem Lauf; weder Antwortreihenfolge, Datenschutzklasse noch aktuelle
Auswahl dienen als Beleg. Streamereignisse liefern dieselben Werte. Interne
Systemantworten ohne gesondertes Antwortmodell sind markiert. Nicht erfasste
oder mehrdeutige ältere Zuordnungen bleiben ausdrücklich unbekannt.

Migration0027 rekonstruiert Altzuordnungen nur aus exakt identischen, eindeutig
gespeicherten Delta-Ereignissen innerhalb desselben Gesprächs. Anbieter-Aliase
wie automatische Modellrouten werden als Anfragekennung angezeigt; ein vom
Anbieter nicht gemeldetes aufgelöstes Modell wird nicht erfunden. Die öffentliche
Demonstration ist synthetisch und belegt keine reale Cloudintegration.


Abnahme 10.10.2026: Release77b9d98 / Schema0027 auf Test-VM installiert.
CI38047407010 mit 610 Tests/13 Browserprüfungen erfolgreich. Bestehende Anmeldung
und Passwortformular ohne echten Passwortwechsel bestätigt. Echte lokale
Modellantwort plus Herkunftshinweis nach Reload geprüft, QA-Chat archiviert.
Vorheriges Backup off-VM hashgeprüft, Originalnachrichten per strukturiertem
Digest bewahrt; Overlays und Netzwerkregeln unverändert. Cloudtests bleiben
synthetisch. Wiederhergestellte Teilantworten behalten ihre echten Laufdaten.


## 10.10.2026: Durchgehende Arbeitsraumsuche

Nächster offener Planbaustein umgesetzt: Suchknopf im Header und ⌘K/Strg+K,
lokale Suchpalette mit sechs Objektfiltern, Tastatur/Fokus, Loading/Fehler/Leerzustand
und direkter Objektöffnung. Gespräche (aktive Nachrichtentexte), Projekte
(Beschreibung), aktuelle Aufgaben (Ziel), Dateititel, Quellnamen und
Wissensverbindungen (Name/Typ) sind auffindbar. Native Dokumentvolltexte,
Einstellungen und Zugangsdaten werden nicht durchsucht. Suchtexte werden nicht
in Navigations-URLs, Browserentwürfen oder serverseitiger Historie gespeichert.

API liefert ausschließlich begrenzte Navigationsmetadaten, maximal 30 Treffer,
keine Inhaltsauszüge. Literalzeichen/Unicode, Archiv-/Versionsgrenzen und
pausierte Wissensverbindungen sind geprüft. Die Suche führt weder Modelle noch
Aktionen aus. Vorschauprüfung bleibt ausdrücklich unbestätigt. Wiederholtes
Öffnen und Reload funktionieren; vorhandene Chatentwürfe bleiben erhalten.
Ungespeicherte Änderungen bestehender Aufgaben verlangen beim Trefferwechsel
Bestätigung; dies ersetzt noch keine geräteübergreifende Entwurfssynchronisierung.

Startübersicht, zusätzliche Suchtypen, Dokumentvolltextsuche/Versionsvergleich, zusätzliche Profile
und breitere Geräte-/Modellabnahme bleiben offene nächste Bausteine.


Abnahme der Suche: Releasea698d72 / Schema0027, CI38050170365: 620 Tests und
15 Browserprüfungen bestanden. Bestehende Test-VM installiert; echte lokale
Antwort, deren Suchtreffer und direkte Gesprächsöffnung über HTTPS bestätigt.
Sicherung off-VM geprüft, Originalnachrichten/Overlays/Netzregeln erhalten,
QA-Chat archiviert. Kein Passwortwechsel, keine globale Vorgabenänderung.


## 10.10.2026: Webrecherche ohne wiederholte Bestätigung

Auf ausdrücklichen Benutzerwunsch ist Websuche standardmäßig aktiv. Der Webknopf
schaltet sie unmittelbar; in den Einstellungen lässt sich der im Browser gespeicherte
Standard ändern. Der zusätzliche Suchtextdialog entfällt. Senden, Bearbeiten und
erneut Antworten verwenden jeweils die aktuelle Frage als gebundene öffentliche
Query (getrimmt, maximal die ersten 500 Zeichen). Die aktivierte Option erlaubt
Recherche bei Bedarf; sie erzwingt keinen Suchaufruf für jede Nachricht.
Ein neuer Lauf bewahrt diese Entscheidung; ein wiederholter Versuch fordert
keine zusätzliche Zustimmung an. „Nur lokal“ schaltet Websuche für den Lauf aus,
ohne den gespeicherten Standard zu ändern.

Die Backend-Grenze prüft weiterhin konkrete Query, Laufkennung und Sucherlaubnis.
Private Historie, Dokumente, Vault und Memory werden nicht automatisch als Suchtext
übertragen. Lokale Modellwahl und öffentliche Websuche sind getrennte Entscheidungen;
die Sucherlaubnis genehmigt weder Cloud-Modelltransfer noch andere Werkzeugaktionen.
Abnahme: Release ed911e9 / Schema0027, CI38056148463 mit 648 Tests und
17 Browserprüfungen. Echte UI-Webrecherche und Retry nach Reload ohne Dialog
mit je acht gespeicherten Quellen und lokaler Modellantwort bestätigt.
QA-Chats archiviert, Sitzungen beendet; Backup und vorhandene Plattform bewahrt.


## 10.10.2026: Eigener Einstellungsbereich für Webrecherche

Unter Einstellungen → Webrecherche werden die Suchvorgaben direkt konfiguriert:
serverseitige Aktivierung, Suchsprache (alle, Deutsch, Englisch), SafeSearch,
Trefferanzahl (1–8) und Zeitlimit (5–30 Sekunden). Eine feste öffentliche
Beispielsuche prüft die bestehende Verbindung. Die Suchdienstadresse ist weiterhin
betreiberseitig gebunden; keine freien URLs oder internen Adressen werden aus
dem Dialog übernommen. Revisionierte Speicherung verhindert verlorene Änderungen.

Die serverweiten Vorgaben ergänzen den unter Allgemein gespeicherten persönlichen
Browserstandard. Die Websuche braucht keine zusätzliche Bestätigung je Anfrage;
„Nur lokal“ verhindert weiterhin externe Recherche für den gewählten Lauf.
Abnahme: Release8337ebf / Schema0028, CI38058159977: 667 Tests und
18 Browserprüfungen. Auf der Test-VM wurden Einstellungen, echter Verbindungstest,
Reload und Mobilansicht geprüft; reale Konfiguration unverändert. Migration,
Originalnachrichten-Digest und Off-VM-Sicherung bestätigt.
Details: [Webrecherche-Einstellungen](web-settings.md).


## 10.10.2026: Leseposition während langer Antworten

Der Chat folgt neuen Antwortteilen nur, solange der Benutzer am Gesprächsende
liest. Eigene Aufwärtsbewegungen lösen die Ansicht vom Ende; weitere
Streamingteile, Statuswechsel und die Speicherung der fertigen Antwort sollen
die Leseposition dann bewahren. „Zum Ende“ führt gezielt zur aktuellen Antwort
zurück und setzt das Folgen fort. Der Gesprächsbereich und der Sprungknopf
bleiben per Tastatur erreichbar und berücksichtigen reduzierte Bewegung.

Die Änderung betrifft die Gesprächsansicht, keine Modell- oder Webeinstellungen.
Eine neue Unterhaltung darf ihren eigenen Startzustand erhalten; Entwürfe bleiben
von der Scrollposition unabhängig. Die öffentliche Illustration verwendet einen
längeren isolierten synthetischen Text. Release7cd5e2f / Schema0028: CI38060571213
mit 667 Tests und 19 Browserprüfungen. Echte lokale VM-Antwort mit bewahrter
Leseposition bis Abschluss, Sprung ans Ende und Mobilansicht bestätigt; QA-Chat
archiviert. Langsamer SSE-/Touch-/Tastatur-/Retry-Korpus ist synthetisch geprüft.


## 10.10.2026: Zeitbudget und erhaltene Teilantworten

Lange Antworten erhalten nach Einordnung und Vorbereitung ein separates
Generierungsbudget. Die bisherige gemeinsame 90-Sekunden-Grenze konnte eine
fortlaufende Ausgabe mitten im Text abbrechen. `HUB_RUN_TIMEOUT` bleibt für die
Vorbereitung erhalten; `HUB_GENERATION_TIMEOUT` erlaubt standardmäßig zehn Minuten
für die eigentliche Antwort (Betreiberbereich 30–900 Sekunden). Die vorhandenen
Inaktivitäts- und Ausgabegrenzen bleiben wirksam.

Bei tatsächlichem Abbruch bleibt der bereits erzeugte Text erhalten, einschließlich
Modellbeleg und zugeordneter Quellen. Direkt unter dem Text steht „Teilantwort ·
unvollständig“; Benutzerabbruch erhält „Teilantwort · abgebrochen“. Eine einzelne
Fehlermeldung erläutert Zeitlimit, unterbrochene Providerdaten oder Ausgabegrenze.
Der erneute Versuch bleibt erreichbar, ohne den abgebrochenen Lauf zu einem Erfolg
umzudeuten. Eine ausschließlich synthetische öffentliche Illustration zeigt diese
Darstellung. Abnahme: Release f68ea06 / Schema 0028, CI 38065130872 mit 677 Tests
und 19 Browserprüfungen. Tatsächliche lokale Antwort mit 5.749 Zeichen und
Schlussmarker nach 138,43 Sekunden erfolgreich; Reload ohne Fehler oder falsche
Teilantwortkennzeichnung bestätigt. Eigener QA-Chat archiviert, Sitzung abgemeldet.


## 10.10.2026: Auto mit Cloud und erklärbarem Routing

Auf ausdrücklichen Benutzerwunsch startet der gewöhnliche Chat mit „Auto · Lokal +
Cloud“ und aktivierter Websuche. „Nur lokal“ bleibt direkt erreichbar und verhindert
auch externe Suche für diesen Lauf. Bestehende LOCAL_ONLY-Nachrichten, private
Projekte und Wissenskontexte behalten ihre Grenzen. Vorhandene ausgeschaltete
persönliche Webvorgaben bleiben eine bewusste Benutzerauswahl.

Einstellungen → Routing bietet Auswahlkarten für „Ausgewogen“, „Lokal bevorzugen“
und „Cloud bevorzugen“. Die separate Option für komplexe Recherche steuert den
Komplexitätsaufschlag im ausgewogenen Modus. Änderungen werden revisioniert auf
dem Server gespeichert und gelten für neue Läufe. „Lokal bevorzugen“ bedeutet
lokale Einordnung ohne Aufschlag, nicht die strikte Sperre des Modus „Nur lokal“.

Ein Testprompt erklärt die gespeicherten Regeln ohne Modell- oder Cloudaufruf.
Die Vorschau zeigt Präferenz, effektive Route und begrenzende Regeln; die echte
Einordnung kann abweichen. Neue Antworten speichern ihren Regelstand und die
wirkliche Routingentscheidung in der Laufhistorie. Modellherkunft unter der
Antwort bleibt an tatsächliche Laufdaten gebunden.

Die öffentliche UI-Illustration verwendet einen ausschließlich synthetischen
Prompt zum Beispielprojekt Aurora. Release db3f8a0 / Schema0029 ist auf der
Test-VM bestätigt: CI38070872371 mit695Tests und20Browsersuiten; tatsächliche
kurze öffentliche Recherche mit acht Webquellen und OpenRouter-Antwort erfolgreich,
Routingvorschau und Reload geprüft. Der QA-Suchtext war ausdrücklich für den
synthetischen Test gewählt; detaillierter Umfang und Grenzen stehen in STATUS.


## 10.10.2026: Persönliches Profil und einfachere Skill-Dateien

Einstellungen → Über mich bietet freiwillige Felder für Name, Anrede, Beruf, Familie,
Herausforderungen, Ziele, Interessen und weitere Hinweise. Das Profil startet leer
und ausgeschaltet. Lokal werden aktivierte Angaben berücksichtigt; Cloudantworten
erhalten nur ausdrücklich freigegebene Felder. Entwürfe, Konflikte, Verlaufnavigation
und bewusstes Leeren sind geschützt. Hintergrunddaten werden nicht automatisch
zu Suchtexten oder Titel-/Routinginformationen. Details: [Persönliches Profil](personal-profile.md).

Die neue Skill-Bibliothek ist über die Hauptnavigation und Einstellungen → Skills
erreichbar. Vorlagen, Suche, Filter, strukturierter Editor und Markdown-Vorschau
ersetzen die bisher primär technische Oberfläche. Einzelne SKILL.md-Dateien mit
YAML-/JSON-Frontmatter oder reines Markdown lassen sich als ungeprüfte Entwürfe
importieren. Jede Revision erhält die Verwendung Immer/Bei Erwähnung/Nach Stichwort
und eine eigene Cloudentscheidung. Speichern & aktivieren bindet die bewusste
Prüfung atomar an den Inhalt. Entfernen archiviert statt alte Laufbelege zu löschen.
Chat → + → Skill einsetzen fügt einen expliziten Aufruf in die Nachricht ein und
beachtet vorhandene Gesprächsauswahlen. Details: [Skills](skills.md).

Synthetische Browser-/API-Abnahme und echte releasegebundene VM-Belege werden
in STATUS getrennt dokumentiert. Eine vollständige Unterstützung ausführbarer
Claude-Skillpakete oder eine automatische Verarbeitung privater Quellen wird
nicht behauptet.


## Neutrale visuelle Überarbeitung –10.10.2026

Weiß/Grau und Graphit ersetzen die grüne Grundgestaltung. Indigo markiert nur
Auswahl, Fokus und wichtige Aktionen; Nutzertext bleibt auf neutraler Fläche.
Seitenleiste ist im Hellmodus hell, im Dunkelmodus anthrazit. Gemeinsame Tokens
verbinden Chat, Karten, Profile, Skills und Dialoge. Sans-Serif-Starttypografie,
ruhiger Composerfokus und konsistente Textkontraste begleiten die bestehenden
Bedienabläufe. Die öffentliche Vorstellung und sämtliche18synthetischen Bilder
werden mit derselben Lieferung aktualisiert. Releasebelege stehen in STATUS.
