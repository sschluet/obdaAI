# Recherche und lokale Datei in einem Auftrag

Ein aktives Projektgespräch kann eine ausdrücklich freigegebene öffentliche Websuche
mit der Erstellung eines neuen Word-Dokuments, einer Präsentation oder einer
Inhalts-PDF kombinieren. Der normale Quellen-Dropdown bestätigt weiterhin den
genauen neuesten Nachrichtentext; fehlende Zustimmung und „Nur lokal“ verhindern
den externen Suchaufruf. Private Historie und Projekttexte werden nicht zur Suche
beigefügt. Andere Aufgaben/Systemwerkzeuge werden nicht implizit kombiniert.

Suchergebnisse mit URL, Titel, Abrufzeit und Inhalt werden dauerhaft am selben Lauf
gespeichert. Maximal vier tatsächlich verwendete Suchauszüge mit je 800 Zeichen und
zusammen 3000 Zeichen Quellenreferenzen werden ausdrücklich als untrusted und
LOCAL_ONLY in den lokalen Dateientwurf eingebunden. Optional ausgewählte
Projektoriginale behalten eigene Revisionen, Hashes und Fundstellen. Das Modell
kann diese Bindungen nicht ändern. Die 30-Minuten-Entwurfquittung bindet die gesamte
Recherche per Hash; Drift, Abbruch, neue Frage und Projektwechsel verhindern den
letzten Schreibpunkt. Im Dialog können diese neuen Belege nicht frei eingegeben
oder durch eine fremde Recherche ersetzt werden.

Word/PDF erhalten die verwendeten Referenzen in einem eigenen Quellenabschnitt,
PowerPoint in den Foliennotizen. Die Oberfläche zeigt sie im Herkunftsbeleg.
Die Ausgabe bleibt lokal und benötigt alle Vorschauseiten sowie explizite
Downloadfreigabe. Suchauszüge sind kein Beleg für das vollständige Lesen einer
Webseite oder allgemeine Faktentreue. Physische PDF-/Bildoperationen und Änderungen
einer bestehenden Dateiversion werden nicht zugleich mit neuer Recherche gemischt.

Getrennte Abnahme: API-/Privacytests prüfen den exakten Suchtext, lokale Verarbeitung,
Referenzen, fehlende Freigabe, leere Ergebnisse und Drift. Die Browser-Fixture
prüft die normale Quellenbestätigung und Herkunftsanzeige; echte Recherche-, Modell-
und Linux-Dateiabnahme müssen zusätzlich auf der eigenen Installation erfolgen.

Fortlaufende Dateiplanung nutzt das konfigurierte Run-Gesamtzeitlimit (höchstens
120 Sekunden für einen direkten Entwurf). Im Chat bleibt das gemeinsame Run-Limit
einschließlich Router und Suche maßgeblich. Der Provider-Timeout begrenzt weiterhin
einen stillstehenden HTTP-Empfang. Ein abgelaufenes Entwurfslimit erzeugt keine
Dateiversion und keinen automatischen Modellretry. Beide Zeitgrenzen sind getestet.

Ein eindeutiger direkter Auftrag wie „Recherchiere öffentlich … und erstelle …“
verlangt die reale Websuche auch dann, wenn das lokale Modell nur Retrieval und
Dateierstellung klassifiziert. Die Regel ergänzt keine Suchrechte: ohne bestätigten
aktuellen Suchtext wird vorher abgebrochen. Zitate, Projektquelltexte und reine
Projekt-Recherche lösen diese Regel nicht aus. Die Dateiplanung wird ausdrücklich
über die bereits abgeschlossene Suche informiert. Tests prüfen beide Freigabewege.

Der Quellen-Dropdown enthält einen getrennten, editierbaren öffentlichen Suchtext.
Der angezeigte Themenvorschlag wird erst nach expliziter Bestätigung gesendet.
Der Dateiauftrag bleibt im lokalen Gespräch. API-Clients können `web_query` zusammen
mit `web_search_allowed` übergeben; ohne Bestätigung bzw. bei „Nur lokal“ wird er
abgewiesen. Bestehende Clients ohne eigenes Suchfeld behalten den ausdrücklich
bestätigten vollständigen Nachrichtentext. Query und Inhalt sind am unveränderlichen
Run-/Recherchebeleg gebunden; eine geänderte Query unter derselben Anfragekennung
wird vor dem zweiten Suchaufruf abgewiesen. Quellenrelevanz und Faktentreue müssen
zusätzlich geprüft werden: korrekte Hashes beweisen keine sachliche Richtigkeit.

Eine ausdrücklich eingegebene `site:domain`-Beschränkung wird zusätzlich an den
HTTPS-Ergebnisdomains geprüft. Fremde Treffer und ähnlich aussehende Hostnamen
werden verworfen; der bestätigte Suchtext wird dabei unverändert gesendet.
