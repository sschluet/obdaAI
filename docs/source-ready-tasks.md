# Aufgaben bei neuen Projektdokumenten

Im normalen Aufgabendialog kann unter Ausführung „Wenn ein neues Projektdokument
bereit ist“ gewählt werden. Ein Projektraum und lokale Arbeitsraumprüfungen oder
KI-Analysen sind erforderlich. Die Aufgabe wird zunächst pausiert gespeichert;
der Dokumentauslöser braucht eine bewusste Aktivierung und einen gesunden Zeitimpuls.
Die bestehende n8n-Uhr übermittelt weiterhin nur den unveränderten leeren Tick.
Es werden keine Dokumentinhalte, Dateinamen oder Aufgaben an n8n übertragen.

Schema 0022 speichert die erste erfolgreiche Verarbeitung eines unveränderten
lokalen Originals als SourceReadyEvent: Projekt-ID, Quellen-ID, Revision, SHA und
Zeitpunkt. Die Extraktion, Fundstellen und das Ereignis werden gemeinsam unter
kurzem Aufgabenlock committed. Ereignis-IDs sind dadurch in Commitreihenfolge;
Original-ID/SHA sind eindeutig. Wiederholte Verarbeitung erzeugt kein zweites
Ereignis. Schon vor Einführung fertig eingelesene Originale werden als Baseline
markiert und lösen keine neuen Aufgaben aus. Das historische Baseline-Datum ist
das Uploaddatum, kein behaupteter ursprünglicher Extraktionszeitpunkt.

Aktivierung setzt den Ereigniscursor auf den aktuellen Stand. Frühe oder während
einer Pause entstandene Ereignisse werden nicht nachgeholt. Der nächste interne
Tick registriert neue passende Ereignisse; nach 120 Sekunden sind sie verpasst
und erhalten einen Übersprungbeleg. Ein bereits aktiver Lauf verhindert einen
weiteren parallelen Lauf; das Ereignis bleibt mit Begründung in der Historie.
Pro Tick werden insgesamt höchstens 200 Ereignisse und je Plan 100 berücksichtigt.
Keine unbeschränkte externe Event-URL, kein fremder Webhook und kein Cloudfallback.

Cursor, Ereignisbeleg, unveränderte Aufgabe und dauerhafte Workerqueue werden in
einer Transaktion gespeichert. Doppelimpuls oder Workerretry erzeugt keinen neuen
Lauf. Aufgabe, Projekt, Quellen, Skills, Auslöserrevision, Pause/Archiv und das
konkrete Original werden am Worker erneut geprüft. Die neue Quelle wird nicht
implizit in den Analysekontext aufgenommen: Nur bereits ausdrücklich ausgewählte
Quellen mit ihren unveränderten Revisionen/Hashes stehen der lokalen Analyse zur
Verfügung. Schreibprofile und HA-/externe Schritte sind für diesen Auslöser gesperrt.

Die Aufgabenansicht bietet den Filter „Bei neuen Dokumenten“; Ereignishistorie und
Laufergebnis sind verknüpft. Ein fehlender Zeitimpuls verhindert Aktivierung.
Weitere Ereignistypen und automatische Analysen neu hochgeladener Inhalte benötigen
einen eigenen begrenzten Vertrag; sie sind nicht durch diesen Auslöser freigegeben.
