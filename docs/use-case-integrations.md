# Use Cases mit Integrationen und KI-Erstellungsdialog

Unter Use Cases → Mit KI erstellen einen Ablauf beschreiben. Der Erstellungsdialog
verwendet das tatsächlich gewählte Modell, stellt bei Bedarf Rückfragen und erzeugt
einen validierten Vorschlag. „Vorschlag prüfen und bearbeiten“ übernimmt ihn in den
Editor; erst „Use Case speichern“ legt eine Definition an. Der Dialog startet lokal,
kann bewusst Auto/Cloud verwenden und legt keine Integrationszugänge selbst an.
Eine aktive Sitzung kann abgebrochen und ein abgeschlossener Dialog wiederaufgenommen
werden. Ungültige Modellantworten bleiben als Rohtext mit Erklärung sichtbar.

## Integrationen auswählen

Im Editor stehen getrennte Bereiche für Material aus Integrationen, Kontext für
die Bearbeitung und Ergebnisweitergabe bereit. Projektbezug bleibt optional;
bestehende Projektquellen und Projektintegrationen werden zusätzlich berücksichtigt.
Eingabe/Bearbeitung lesen aktuell aktivierte und erfolgreich geprüfte Paperless-
Profile. Andere Adapter sind sichtbar gesperrt. Beide Bereiche liefern privaten
Archivkontext; beliebige API-Befehle oder Shell-Aktionen werden nicht ausgeführt.
Auswahl und Revisionen sind an den Lauf gebunden. Änderung oder Abschalten stoppt
laufende Verarbeitung; private Archivinhalte und ihre Ableitungen bleiben lokal.

## Mailversand

Unter Einstellungen → Integrationen eine SMTP-Verbindung mit Servername, Benutzer,
Passwort und Absenderadresse anlegen. Port465 nutzt SSL/TLS, Port587 zwingend
STARTTLS vor der Anmeldung. Zugangsdaten werden verschlüsselt gespeichert. Nach
Aktivierung prüft „Zugang prüfen“ TLS und Anmeldung, ohne eine Nachricht zu senden.
Eine geprüfte Verbindung kann als primärer Mailversand festgelegt werden.

Für die Ergebnisvorschau gilt: ausdrückliche Vorschauauswahl, feste Use-Case-Ausgabe-
verbindung, eindeutig benannte Verbindung im definierten Auftrag, primäre Verbindung.
Beispiel: „Mailversand über Firmenpost“. Der Name muss einer vorhandenen Verbindung
entsprechen. Mehrdeutige oder deaktivierte gewählte Verbindungen werden erklärt;
unbekannte Namen ändern die primäre Auswahl nicht. Integrations-IDs aus KI-
Erstellungsvorschlägen werden nicht automatisch übernommen.

Nach erfolgreicher Verarbeitung Empfänger und Betreff eingeben und die Vorschau
öffnen. Sie zeigt tatsächliche Verbindung, Absender, Empfänger und den genauen
Ergebnistext einschließlich Tabellenwerten. Die Mail ist eine Textnachricht;
CSV-/Excel-Dateien können weiterhin separat heruntergeladen werden. Erst
„Jetzt E-Mail senden“ gibt diese Ausgabe an den Mailserver weiter.

Die Vorschau läuft nach15 Minuten ab. Änderungen an Ergebnis, Definition,
Verbindung oder verwendeter primärer Auswahl machen sie ungültig. Versandquittungen
verhindern dieselbe Übergabe bei wiederholten Anfragen. „Vom Mailserver angenommen“
belegt die SMTP-Übernahme, nicht die spätere Zustellung. Bei unklarer Übernahme gibt
es keine automatische Wiederholung; vor erneutem Versand Postausgang prüfen.
Versand, der nach fünf Minuten keinen Abschluss hat, wird als unklar eingeordnet.
Laufender Versand blockiert die Use-Case-/Projektlöschung; eigene Vorschau- und
Quittungsdaten werden bei bestätigter Löschung mit bereinigt.

Netzwerkziele stammen ausschließlich aus aktivierten, menschenkonfigurierten
Integrationsprofilen. TLS-Hostname und Zertifikatsprüfung bleiben trotz numerischer
Zielbindung erhalten. Kein Modelltext kann beliebige Mailserver oder Transport-
optionen wählen. Externe Testmails erfordern einen konkreten Auftrag; synthetische
Transportprüfungen sind in STATUS getrennt von echten Serverprüfungen dokumentiert.
