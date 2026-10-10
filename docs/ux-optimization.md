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

- Durchgehende Suche über alle Objekttypen und umfangreichere Startübersicht.
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
