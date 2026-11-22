# Google Drive als optionale Verbindung

Google Drive wird unter **Einstellungen → Integrationen → Verbindung hinzufügen →
Google Drive** eingerichtet. Die Verbindung bleibt ohne Einrichtung ungenutzt.
Es werden beim App-Start keine Google-Anmeldung, Indexierung oder Uploads ausgelöst.
Die vorhandene Gmail-Verbindung und deren Rechte bleiben getrennt.

## Einrichten

1. Im eigenen Google-Cloud-Projekt die **Google Drive API** aktivieren und einen
   OAuth-Client des Typs **Webanwendung** einrichten. Einen bestehenden Gmail-Zugang
   nicht mit einem Drive-Zugriff gleichsetzen.
2. Den Dialog in obdaAI öffnen und die dort angezeigte exakte Weiterleitungs-URL
   beim Google-Client hinterlegen. Der Rückruf lautet
   `/api/integrations/google-drive/callback`; die Basis kommt ausschließlich aus
   der serverseitig festgelegten App-Origin. Produktion benötigt HTTPS; lokale
   Entwicklung unterstützt `http://127.0.0.1`.
3. Client-ID und Client-Secret eintragen und ausdrücklich auswählen, ob Drive als
   **Wissensquelle**, **Dateiablage** oder für beides verwendet werden soll.
4. Speichern und **Mit Google verbinden** wählen. Anmeldung und Kontowahl erfolgen
   direkt bei Google. Das Secret und die Tokens bleiben verschlüsselt in der
   vorhandenen Integrationsablage; sie werden weder an die KI noch an den Browser
   zurückgegeben.

Der Dialog zeigt die benötigten Berechtigungen: `drive.readonly` für Quellen und
`drive.file` für selbst angelegte Ablagedateien. Die App akzeptiert ausschließlich
zur gewählten Nutzung passende Tokens. Die Ablage erlaubt keine beliebigen
Änderungen oder Löschungen an vorhandenen Drive-Dateien.
[Google beschreibt die Unterschiede der Drive-Berechtigungen](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

Bei externen Google-OAuth-Apps im Status **Testing** können Refresh-Tokens nach
sieben Tagen ablaufen. Testbenutzer und Veröffentlichungsstatus im eigenen
Google-Projekt beachten; bei abgelaufenen oder widerrufenen Rechten erneut
verbinden. Unklare Token-Erneuerungen werden nicht blind wiederholt.
[Google OAuth: Token-Gültigkeit](https://developers.google.com/identity/protocols/oauth2).

## Als Wissensquelle verwenden

Nach der Anmeldung einen Ordner durchsuchen oder seine ID eingeben und
**Ordner als Wissensquelle einlesen** wählen. Ein für das gesamte Konto
freigegebener Quellenbereich (`root`) kann auf den gewählten Unterordner
beschränkt werden, ohne sich erneut anzumelden. Ein enger voreingestellter
Quellenbereich darf darüber nicht verlassen werden.

Die Verbindung nutzt den vorhandenen Wissensbereich mit eigenem Quellenprojekt,
Dateiversionen, lokaler Extraktion und Fundstellen. Die Oberfläche ist unter
**Wissen → Wissensquellen** erreichbar. Nach der Indexierung kann ein Quellenchat
geöffnet werden. Inhalte bleiben `LOCAL_ONLY`; sie gelten als nicht
vertrauenswürdige Daten, niemals als Systemanweisungen oder persönliche Fakten.

Ein Abgleich berücksichtigt **direkt im gewählten Ordner liegende unterstützte
Dateien**, keine rekursiven Unterordner oder Drive-Verknüpfungen. Im Dialog werden
bis zu 50 Dateien pro Abgleich angefordert; die API erlaubt begrenzte größere
Batches mit höchstens 20 Listenseiten. Google Docs, Sheets und Slides werden als
DOCX, XLSX beziehungsweise PPTX exportiert; andere unterstützte Dateien werden
als Original eingelesen. Einzelne Antworten sind auf 25 MiB begrenzt; native
Google-Exporte unterliegen zusätzlich Googles Exportgrenze.
[Google: Downloads und Exporte](https://developers.google.com/workspace/drive/api/guides/manage-downloads).

Bei einem Wechsel des Ordners oder der Kontobindung werden alte Momentaufnahmen
aus dem aktiven Quellenbereich genommen. Ihre Originalbytes bleiben erhalten.
Wartende oder gerade abschließende Extraktionen dürfen solche Quellen nicht
reaktivieren; auch die Retry-API lehnt das ab. Ein unveränderter Abgleich ist kein
Löschspiegel für remote entfernte Dateien. Bereits gespeicherte Chatantworten
bleiben Historie.

Deaktivieren oder Trennen sperrt neue Zugriffe. Quellenrechte und Revisionen
werden auch unmittelbar vor einem Modellaufruf erneut geprüft, einschließlich
Wartezeit auf das lokale Modell. Ein neu angelegter Ablageordner oder ein
Aus-/Einschalten mit unveränderten Quellenrechten zerstört keine bestehende
Wissensquelle.

## Als Dateiablage verwenden

Im Drive-Dialog zunächst den eigenen **obdaAI-Ablageordner erstellen**. Die App
prüft dessen Herkunft, Besitzer, aktuelle Schreibmöglichkeit und gespeicherten
Übertragungsnachweis. Ein gleichnamiger fremder Ordner wird nicht übernommen.

Bei einer vollständig erzeugten Datei **In Google Drive speichern** wählen.
Der Dialog bindet die ausgewählte Dateiversion, das verbundene Konto und den
Ablageordner. Die Übertragung muss für diese konkrete Datei ausdrücklich
bestätigt werden. Diese Freigabe gestattet den Dateitransfer zu Google und
**ändert keine Freigabe gegenüber externen KI-Modellen**.

Es werden neue Dateien bis **25 MiB** angelegt, vorhandene Dateien nicht
überschrieben. Original, lokale Version, Vorschau und bisheriger Prüfstatus
bleiben erhalten. Google erhält die eigentlichen geprüften Dateibytes; der Upload
konvertiert keine Office-Datei in ein natives Google-Dokument.

Jeder Ordner-/Uploadauftrag besitzt eine dauerhafte Absicht mit Request-ID,
Profilrevision, Ziel und Hash. Google-Datei-IDs werden vor dem Schreiben reserviert.
Nach einem unklaren Ergebnis wird nur dieselbe ID lesend abgeglichen; es gibt
keinen blinden erneuten POST und keinen automatischen neuen Auftrag. Den Status
im Drive-Dialog aktualisieren. Ein unbekannter Ausgang wird nicht als Erfolg
angezeigt.
[Google: Reservierte Datei-IDs](https://developers.google.com/workspace/drive/api/guides/create-file).

## Betrieb und Nachweise

Die bestehende Serverfreigabe `HUB_INTEGRATION_TARGETS_ENABLED` und die vorhandene
Secret-Verschlüsselung sind erforderlich. Benötigt werden ausschließlich die
festen Google-OAuth- und Drive-API-Endpunkte; keine frei konfigurierbaren URLs.
Bestehende Egress-Regeln müssen deren Zugriff erlauben. Diese Lieferung verändert
keine Firewall und startet die derzeit unerreichbare Test-VM nicht.
Access-Logs mit OAuth-Querystrings nicht einschalten; die bestehenden Docker- und
Nginx-Vorlagen deaktivieren sie. Google-Rohfehler, Codes und Tokens gehören nicht
in Diagnoseausgaben.

Migration **0047** ergänzt ausschließlich zwei Tabellen für OAuth-Versuche und
Übertragungsnachweise in derselben Datenbank. Vor einer Ausrollung sichern und
explizit migrieren. Ein Downgrade mit vorhandenen Drive-Profilen, OAuth-Zuständen
oder Übertragungsnachweisen wird abgelehnt. Alte App-Versionen verstehen den
neuen Integrationstyp nicht; nach einer Einrichtung keinen unkontrollierten
App-Rollback auf einen älteren Stand durchführen und keine Daten löschen, um
Rollback zu erzwingen.

Gezielte API-, Transport-, UI- und Migrationsfälle sind synthetisch geprüft.
Google-spezifische Browserantworten sind ausdrücklich simuliert; Quellenspeicher,
Extraktionsweg und gerenderte Testdateien werden zusätzlich durch Backendtests
geprüft. Eine persönliche Google-Anmeldung, echter Dateiabruf/Upload und die
Ausrollung auf die Test-VM sind noch nicht abgenommen. Den aktuellen exakten
Gesamtprüfungsstand führt `STATUS.md`.
