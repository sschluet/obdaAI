# Sicherheitsmodell

## Verbindliche Labels
`LOCAL_ONLY` ist Standard; `CLOUD_ALLOWED` gilt ausschließlich für explizit
freigegebene Scope/Revision/Ziel-Kombinationen. Ableitungen behalten die strengste
Quellregel. Das gilt für Historie, Auszüge, Zusammenfassungen, Titel, Embeddings,
Suchanfragen, Logs, Screenshots und Workflowausführungen. Kein automatischer
Sensitivitätsdetektor kann Labels lockern. Ein Routervorschlag ist keine Freigabe.

Die auf Benutzerwunsch standardmäßig eingeschaltete Websuche ist eine dauerhafte,
im Browser abschaltbare Erlaubnis für den aktuellen eingegebenen öffentlichen Suchtext.
Jeder Lauf bindet die konkrete Query und Sucherlaubnis; private Historie, Dokumente,
Vault und Memory werden nicht automatisch einbezogen. „Nur lokal“ sperrt die Suche
für diesen Lauf. Diese Erlaubnis erweitert keine Cloud-Modell-, URL- oder Aktionsrechte.

Der Provider-Gateway prüft direkt vor HTTP-Ausgabe den gesamten tatsächlich
ausgehenden Payload und alle Quelldeklarationen. Lokaler Ausfall endet mit Fehler,
niemals Cloud-Fallback. Unbekannte Preise bleiben null/unbekannt. Quellen-/Tooltexte
sind untrusted data. Keine Installation oder Rechteänderung aus Modelltext.

## Ausführung und Authentifizierung
Single-User Passwort-Login mit scrypt, opaque zufällige Sessions als DB-Hash,
HttpOnly/SameSite-Cookie, Secure in Produktion, exakter Origin und CSRF-Header bei
Mutationen, Ablauf/Logout und begrenzte Loginversuche. UI enthält keine Secrets.
Secrets nur in serverseitigen Dateireferenzen oder AES-GCM-verschlüsselt mit externem
Schlüssel. Serverkonfiguration ist keine allgemeine URL-Freigabe: Ziele konkret
allowlisten, Redirects deaktivieren, DNS-Rebinding/Metadaten-/Managementziele blockieren.
Private Netzwerke nur für explizite Verbindungen; Browser darf API-Regeln nicht umgehen.

## Dateien und Runner
Originale unverändert, Hash und Fundstellen; Dateilimits und Formatprüfung vor Parsing.
Keine Makros, aktiven Inhalte, Archive ohne sichere Expansion, Symlinks oder Traversal.
Artefaktdownloads und Runzugriff sind autorisiert. Runner non-root, no-new-privileges,
read-only rootfs, CPU/RAM/PID-Limits, temporäres Verzeichnis, kein Netz standardmäßig.
Modellgenerierter Code wird nicht ausgeführt. Live-Schwärzung erst nach Inhaltsprüfung.

## Autonome Änderungen
Global pause am Aktionsgateway. Profile: Analyse / Einzel-Freigabe / begrenzt autonom.
Freigabe bindet Aktion, Parameterhash, Revision, Systeme, Zeitraum, Versionen und
Backup-Bedingungen. Änderung benötigt neue Prüfung. Idempotenz und Zustandsabgleich;
unklarer Write-Ausgang wird nicht blind wiederholt. HA-Updates nur nach verifiziertem
Installationstyp, abgeschlossener geprüfter Sicherung und erlaubtem Versionsumfang.
Kein Self-Deployment. Warnungen und Ergebnisse bleiben im Task-Center.

## Nachweise vor Produktivbetrieb
Negativtests zu Cloud, SSRF, Dateipfaden, Login/CSRF, Prompt Injection und
Workflow-Bypass; Rollback/Restore in Isolation. CI und lokales Secret-Scanning.
Privates GitHub ist kein Backup. Bestehende Zugänge nicht ändern oder entziehen.
