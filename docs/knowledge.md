# M2: Projekte, Quellen und kanonisches Memory

Projekte isolieren Chats, Originaldateien, Fundstellen, Webrecherchen und zugeordnetes
Memory. Globale Memories werden nicht automatisch einem Projektchat beigemischt. Ein ausdrücklich
über den Wissensbereich gestarteter globaler Vault-Chat liest ausschließlich diesen
Bereich lokal; normaler Chat und Projektchat erhalten ihn nicht automatisch.
Alle Projekt-, Quellen-, Memory- und Antwortableitungen bleiben LOCAL_ONLY.
Ein Projektgespräch lässt sich nicht pauschal für OpenRouter freigeben.

## Dateien und Nachweise

DOCX/PPTX/PDF/CSV/XLSX/MD/TXT sowie PNG/JPEG/WebP/TIFF werden unverändert und mit
SHA256 gespeichert. Alte Office- und Makroformate werden abgewiesen. Limits: 40 MiB
pro Datei, 100 Dateien / 200 MiB pro Projekt, 2 GiB Originaldateien insgesamt;
zusätzlich Seiten-, Tabellen-, Bildpixel-, ZIP-Verhältnis-, Text-, Zeit- und RAM-Grenzen.
Die Dateigröße erweitert nicht die Extraktionsgrenzen: PDF bis 100 Seiten, höchstens
800.000 Textzeichen und 2.000 Fundstellen; Office-Archive bis 80 MiB entpackter Inhalt
und 20 MiB je Archiveintrag. Eingaben für separate Dateioperationen bleiben auf
20 MiB je Original beschränkt; der Paperless-Download hat ebenfalls sein eigenes
20-MiB-Limit. Diese Grenzen sind unabhängig vom Projektquellen-Upload.
Downloads prüfen den Originalhash und autorisieren den Projektscope. Erneute Verarbeitung
erstellt eine neue Extraktionsrevision und verwendet keine alte Ergebnis-/Fehlercachedatei.

Die PostgreSQL-Queue dispatcht Extraktion atomar mit dem Source-Datensatz. Ein eigener
Source-Worker hält Parsing vom Chat-Inference-Slot getrennt. Der Offline-Parsercontainer
hat kein Netzwerk, keine Datenbank-/Provider-/Vault-Secrets und schreibgeschützte
Originale. Der eigentliche Prozess erhält Linux-Landlock-Regeln nur für die eine Datei,
seine Runtime und seinen temporären Arbeitsbereich. Fehlende Landlock-Unterstützung
unter Linux bricht ab; macOS ist ausschließlich Entwicklungsbetrieb ohne diese Garantie.

Fundstellen tragen Originalhash und ID: PDF-Seite, Foliennummer, Dokumentabschnitt
oder Tabelle, Sheet/Zellbereich, CSV-Zeile, Markdown-Überschrift/Zeile. Text wird direkt
extrahiert; textlose PDF-Seiten und Bilder erhalten lokale Tesseract-OCR. OCR kann
fehlerhaft sein; Bild- und Diagrammsemantik sowie komplexes Office-Layout werden nicht
als verstanden behauptet. Office-Formeln werden erhalten, nicht ausgeführt. ZIP-Makros
und eingebettete aktive Office-Inhalte werden abgewiesen; kein Dokumentcode läuft.

Recherche begrenzt Fundstellen vor dem Modellkontext und wendet den Projektscope im
Datenbankquery an. Die Originaldateien bleiben vollständig gespeichert; eine Antwort
bekommt ausgewählte Auszüge statt aller Dokumenttexte. Die Auswahl berücksichtigt
die aktuelle Frage und das verfügbare Kontextbudget. Suchbegriffe werden mit Dateinamen
und Fundstellentexten im gesamten Projektscope abgeglichen, bevor die Treffer begrenzt
werden. Häufige Fragewörter bestimmen die Relevanz nicht allein. Größere Fundstellen werden als
begrenzte Textfenster übernommen, wobei Quellen-ID, Extraktionsrevision, Dateiname und
Fundstelle erhalten bleiben. Das Antwortmodell erhält einen Hinweis, wenn nur Auszüge
oder eine Auswahl vorliegen, und darf daraus keine vollständige Dokumentprüfung ableiten.

Die Oberfläche zeigt die tatsächlich verwendeten Quellen getrennt vom Modelltext.
Das ermöglicht Fragen in Projekten mit vielen Dateien innerhalb der bestehenden
Upload- und Speichergrenzen; es erweitert weder das Modellfenster noch die Parsergrenzen.
Allgemeine Fragen oder Übersichtswünsche erhalten eine begrenzte Quellenauswahl und
können weitere gezielte Nachfragen erfordern. Die Suche ist textbasiert; semantische
Embeddings und eine erschöpfende Gesamtauswertung aller Dateien werden nicht behauptet.
Zeilenbasierte Tabellenprüfungen summieren mittels Decimal, mit jeder Originalzelle und
ausgelassenen Überschriften/Formeln als überprüfbarem Beleg. Diese Prüfung ersetzt keine
Fachprüfung komplexer Tabellen oder Rechnungen.

## Web

Der austauschbare JSON-Adapter nutzt den dokumentierten SearXNG-Suchendpunkt.
Die dauerhaft gewählte Websuche erlaubt die aktuelle eingegebene Frage als öffentlichen
Suchtext, ohne erneuten Bestätigungsdialog. Sie ist im Browser standardmäßig aktiv und
in Chateingabe und Einstellungen abschaltbar. Es werden keine Suchtexte automatisch
aus privaten Dateien, Memory oder Historie ergänzt. Quell-URL, Titel, Ergebnistext,
Anbieter und Abrufzeit bleiben projektbezogen.
Ohne konfigurierten/erreichbaren Anbieter wird sichtbar keine aktuelle Recherche behauptet.

Gezielter HTML-Abruf benötigt zusätzlich eine konkrete URL-Freigabe und operatorseitige
Domainliste. DNS wird auf öffentliche IPs geprüft und für Host/TLS-SNI gepinnt; private,
Metadaten- und Linklocal-Ziele, Redirects, URL-Credentials und Querystrings sind gesperrt.
Keine Skriptausführung, Cookies, Umgebungsproxies oder automatische Linkverfolgung.
Webinhalte sind untrusted Daten und erlauben keine Memory-/Skill-/Systemänderungen.

## Obsidian

`HUB_VAULT_DIR` bezeichnet den vorhandenen kanonischen, serverseitigen Vault-Zugang,
keinen zweiten Sync-Dienst. Allgemeine Dateien sind nur lesend. Schreiboperationen
benötigen `HUB_VAULT_WRITABLE=true` und bleiben auf `AI/Memory/` begrenzt. Symlinks,
Traversal, `.obsidian`, Plugins und beliebige Systempfade sind ausgeschlossen.
Der konkrete vorbereitete Zugang steht in `deploy/vault-access-plan.md`.
Ein fehlender Zugang wird sichtbar gemeldet; ein Test-Vault ist keine echte Abnahme.

App-Memory trägt stabile IDs im Markdown-Kommentar sowie DB-Scope/LOCAL_ONLY-Label,
Revision, Hash, Herkunft und historische Fassungen. Vault-Dateien dürfen diese Rechte
nicht selbst erweitern. Reconciliation übernimmt externe Änderungen, Umbenennungen und
Löschungen, erkennt doppelte IDs und hält Tombstones statt alten Inhalt wiederzubeleben.
Minütlicher Wartungsabgleich bündelt Änderungen; der UI-Abgleich ist jederzeit möglich.
Dies ist Indexwartung, keine zweite fachliche Terminierungsengine neben n8n.

Writes vergleichen Revision und Dateihash, persistieren den beauftragten Änderungsintent
und schreiben atomar. Abbrüche werden abgeglichen; abweichende Vault-Inhalte werden als
Konflikt erhalten. Auflösung verlangt den Hash der tatsächlich verglichenen Vault-Fassung.
Versionen bleiben zugänglich; Löschungen eigener Memories verschieben das Original in
`.obdaai-trash` im freigegebenen Memory-Bereich. Externe Sync-Clients honorieren nicht
zwingend den App-Lock; erneute Reconciliation bleibt erforderlich, keine Exactly-once-
oder verteilte Dateisystem-Transaktionsgarantie.

Ein direkt eingegebenes `Merke dir: …` speichert ausschließlich diesen authentifizierten
Benutzertext im Gesprächsscope, lokal und ohne Modellinterpretation. Nachricht-ID und
Revision ergeben eine stabile Idempotenz-ID. Quellen, Modellantworten und Webtexte
können diesen Write nicht auslösen. Automatische Memory-Vorschläge/Übernahme bleiben
deaktiviert. Allgemeiner Vault bleibt readonly; Cloudfreigaben vererben sich nicht.

Webfähige Chatläufe binden `web_search_allowed` und den konkreten öffentlichen
`web_query` an die aktuelle Anfrage (getrimmt, maximal die ersten 500 Zeichen).
Die gewählte Websuche gilt auch für Bearbeitung und Retry; jeder neue Lauf erhält seine eigene aktuelle Query. Chatverlauf, Vault,
Dateiquellen und abgeleitete Routerqueries werden nicht als Suchanfrage übertragen.
„Nur lokal“ setzt Websuche für den Lauf aus. Rechercheergebnisse mit URL und Zeitpunkt
werden als lokale, untrusted Quellen im Lauf gespeichert; der finale Antwortkontext
wird erneut gegen Modellgrenzen geprüft. Ohne angebundenen Suchdienst bleibt die
Funktion gesperrt. Diese Sucherlaubnis erteilt keine Cloud-Modellfreigabe.
Schema 0010 ergänzt explizite globale Vault-Wissenschats, 0011 globale Rechercheläufe.

Bei produktiver SSHFS-Anbindung erzwingt HUB_VAULT_FS_TYPE=fuse.sshfs den tatsächlichen
Mount im Container. Abgleich prüft dessen Identität vor und nach dem Scan; leere
Ersatzverzeichnisse und Transportfehler invalidieren den ganzen Abgleich. Parallele
API-/Worker-Abgleiche werden durch PostgreSQL- und Dateisperren geordnet; persistierte
Schreibintents bleiben vor dem atomaren Dateiaustausch erhalten. Der globale Wissenschat
filtert passende Inhalte vor dem 500-Treffer-Limit, statt ältere Quellen zu übergehen
oder unpassende aktuelle Notizen automatisch beizumischen.

## Einzelne Projektquelle löschen

Im Quellenbereich und im Chat-Arbeitsbereich hat jede Quelle eine Löschaktion.
Die Vorschau nennt Dateiname, Quellenversionen und Indexeinträge. Erst die erneute
Bestätigung entfernt ausschließlich diese lokale Quelle aus dem Projekt und
Suchindex. Originaldatei und alle Parserrevisionen werden über die vorhandene
dauerhafte Bereinigungsqueue entfernt; der Status bleibt auch nach Schließen des
Dialogs sichtbar. Andere Quellen, gespeicherte Antworten, deren Quellenangaben
und abgeschlossene Ausgaben bleiben erhalten. Die entfernte Originalquelle kann
über diese alten Belege nicht mehr geöffnet werden; historische Inhalte werden
nicht umgeschrieben.

Laufende Verarbeitung/Indexierung, aktive Antworten mit diesem Projekt oder dieser
Quelle sowie aktive abhängige Aufgaben, Freigaben und Dateierzeugung verhindern die
Löschung. Eine geänderte Vorschau erfordert eine neue Bestätigung. Bei importierten
Wissenskopien wird nur die lokale Zuordnung entfernt: Verbindung und externes
Original bleiben erhalten, ein erneuter Abgleich kann die Quelle erneut importieren.

Die API bietet `GET /api/projects/{project_id}/sources/{source_id}/deletion` und
`DELETE /api/projects/{project_id}/sources/{source_id}` mit `expected_state`.
Authentifizierung, CSRF und Projektzuordnung gelten unverändert. Die transaktionalen
Ownership-/Aufgabenlocks serialisieren die Mutation mit Verarbeitung und Retry;
verspätete Workeraufträge dürfen entfernte Quellen nicht neu erzeugen.
