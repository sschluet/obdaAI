# Cloudguthaben neben dem Profil

Aktivierte Cloudverbindungen erscheinen dauerhaft unten links neben dem Profil.
Die Detailansicht trennt Kontoguthaben, Schlüsselverbrauch und lokal erfasste Kosten
sowie offene Reservierungen. Salden mehrerer Verbindungen werden nicht addiert:
unterschiedliche Schlüssel können zum selben Konto gehören.

OpenRouter liefert seinen Kontosaldo über die Credits-API nur mit Management Key.
Ein normaler Modellschlüssel zeigt lediglich seine Nutzung und sein Schlüssellimit.
Unter Einstellungen → Modelle → OpenRouter → Kontoguthaben verbinden den zusätzlichen
Schlüssel speichern. Ein direkter Link zur offiziellen Management-Key-Seite ist
vorhanden. Der Schlüssel hat kontoweite administrative Berechtigungen, wird
verschlüsselt separat gespeichert und in obdaAI ausschließlich für lesenden
Kontostatus verwendet. Er wird nicht als Modellschlüssel eingerichtet oder dem
Browser über die Lese-API zurückgegeben.

Ohne Schlüssel steht „Guthaben verbinden“ anstelle eines scheinbaren Nullsaldos.
Bei einem bereits ausdrücklich als Management identifizierten bestehenden Schlüssel
kann der Status dessen vorhandene Berechtigung verwenden. Ein regulärer Schlüssel
wird nicht stillschweigend für Management-Abfragen benutzt. Fehler und fehlende
Berechtigungen bleiben sichtbar; bekannte Werte werden als veraltet gekennzeichnet.

Die sichtbare angemeldete Oberfläche liest initial und alle fünf Minuten den Status.
Externe OpenRouter-Abfragen sind durch einen Servercache von mindestens60 Sekunden
begrenzt. Bei ausgeschalteter Cloud werden keine externen Metadaten abgerufen.
Es werden keine Modellprompts, Gespräche oder Dokumente an diese Endpunkte gesendet;
Statusabfragen erzeugen keine Modellgenerierung. Für andere Anbieter fehlen derzeit
Guthabenadapter; dort sind nur die lokal erfassten Kosten verfügbar.

Referenzen: [OpenRouter Credits-API](https://openrouter.ai/docs/api/api-reference/credits/get-credits),
[aktueller Schlüssel](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key),
[Management Keys](https://openrouter.ai/docs/guides/overview/auth/management-api-keys).
Die tatsächliche Abnahme und verbleibende Einrichtung sind in STATUS getrennt von
synthetischen Tests dokumentiert.
