# M2: Projekte, Quellen und kanonisches Memory

Projekte isolieren Chats, Originaldateien, Fundstellen, Webrecherchen und zugeordnetes
Memory. Globale Memories werden nicht automatisch einem Projektchat beigemischt.
Alle Projekt-, Quellen-, Memory- und Antwortableitungen bleiben LOCAL_ONLY.
Ein Projektgespräch lässt sich nicht pauschal für OpenRouter freigeben.

## Dateien und Nachweise

DOCX/PPTX/PDF/CSV/XLSX/MD/TXT sowie PNG/JPEG/WebP/TIFF werden unverändert und mit
SHA256 gespeichert. Alte Office- und Makroformate werden abgewiesen. Limits: 20 MiB
pro Datei, 100 Dateien / 200 MiB pro Projekt, 2 GiB Originaldateien insgesamt;
zusätzlich Seiten-, Tabellen-, Bildpixel-, ZIP-Verhältnis-, Text-, Zeit- und RAM-Grenzen.
Downloads prüfen den Originalhash und autorisieren den Projektscope.

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
Datenbankquery an. Die Oberfläche zeigt die tatsächlich verwendeten Quellen getrennt
vom Modelltext. Zeilenbasierte Tabellenprüfungen summieren mittels Decimal, mit jeder
Originalzelle und ausgelassenen Überschriften/Formeln als überprüfbarem Beleg.
Diese Prüfung ersetzt keine Fachprüfung komplexer Tabellen oder Rechnungen.

## Web

Der austauschbare JSON-Adapter nutzt den dokumentierten SearXNG-Suchendpunkt.
Nur ein eigens eingegebener und ausdrücklich freigegebener öffentlicher Suchtext wird
übertragen; niemals automatisch aus privaten Dateien, Memory oder Historie abgeleitete
Suchtexte. Quell-URL, Titel, Ergebnistext, Anbieter und Abrufzeit bleiben projektbezogen.
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
