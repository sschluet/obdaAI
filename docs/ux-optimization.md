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
