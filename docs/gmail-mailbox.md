# Gmail-Postfach verbinden

Gmail erscheint unter **Einstellungen → Integrationen → Verbindung hinzufügen →
Gmail**. Ein eigener Assistent führt durch Google-Vorbereitung, OAuth-Client und
Anmeldung. Gmail ist eine Postfachanbindung über die offizielle Gmail API; der
vorhandene SMTP-Typ bleibt ein gesonderter Versandzugang.

## Einmalige Vorbereitung bei Google

1. Ein eigenes Google-Cloud-Projekt anlegen und die Gmail API aktivieren.
2. In Google Auth Platform die App und Zielgruppe einrichten. Für ein privates
   externes Testprojekt das eigene Konto als Testnutzer eintragen.
3. Einen OAuth-Client vom Typ **Webanwendung** erstellen. Die im Assistenten
   angezeigte Weiterleitungsadresse exakt als autorisierte Redirect-URI eintragen.
   Google benötigt eine gültige HTTPS-Adresse; die lokale Entwicklung verwendet
   ausdrücklich Loopback. Keine interne IP als vermeintliche öffentliche Domain
   eintragen, keine fremde Plattform als Callback verwenden.
4. Client-ID und Client-Geheimnis im Assistenten speichern. Beide gehören zum
   eigenen Google-Projekt; ein Google-Passwort oder Zwei-Faktor-Code gehört
   ausschließlich in die Google-Anmeldung.
5. Die sichtbare Auswahl **Gmail lokal lesen und durchsuchen** prüfen und danach
   **Mit Google verbinden** wählen. Google zeigt die angefragte Leseberechtigung.
   Erst nach dem erfolgreichen Rückweg wird der Kontostatus als verbunden gespeichert.

Der erste Aufbau benötigt ein eigenes OAuth-Projekt, weil diese private Anwendung
keinen gemeinsam betriebenen Google-Anmeldedienst hat. `gmail.readonly` ist ein
von Google eingeschränkter Scope. Warnungen, Testnutzer, persönliche Nutzung und
etwaige Verifikationsvoraussetzungen hängen vom Google-Projekt ab. Im externen
Status **Testing** laufen entsprechende Refresh-Tokens nach sieben Tagen ab;
das ist keine dauerhafte unbeaufsichtigte Autorisierung. Google-Projektstatus und
Nutzungsregeln müssen zur tatsächlichen Nutzung passen.

## Nutzung und Grenzen

Die ausdrückliche Leseauswahl erstellt ausschließlich die kontogebundene
`gmail.read`-Freigabe für Profil, Labels, Nachrichtensuche, Nachrichtentext und
Threads. Ausgewählte Verbindungen funktionieren über den gemeinsamen Agentenweg
in Chat, Aufgaben und Projekten. Suchanfragen gehen an Google; Nachrichtentexte,
Betreffzeilen und Ergebnisse bleiben in obdaAI `LOCAL_ONLY`. E-Mail-Inhalte sind
untrusted Daten, keine Werkzeuganweisungen. Keine automatische Cloud-Modellfreigabe.

Dieser Connector versendet keine Nachrichten, ändert keine Labels und löscht keine
Mails. HTML wird nicht als ausführbarer Inhalt gerendert. Anhänge werden zunächst
nur als Metadaten aufgeführt; ein Dateidownload ist nicht Teil dieser Lieferung.
Suchmengen, Pagination, Antwortgröße und Textmenge sind begrenzt. Links und
Anweisungen aus E-Mails werden nicht automatisch geöffnet oder ausgeführt.

**In obdaAI trennen** entzieht die lokale Berechtigung und entfernt Mail-Tokens.
Die Google-seitige OAuth-Erlaubnis kann zusätzlich unter den
[Google-Kontoverbindungen](https://myaccount.google.com/connections) widerrufen werden.
Trennen behauptet keinen erfolgreichen Google-seitigen Widerruf.

## Technische Grenzen und Abnahme

Client-Geheimnis und Tokens sind mit bestehender Serververschlüsselung und
Integrations-ID gebunden gespeichert. Statusantworten enthalten keine Secrets.
OAuth verwendet PKCE, kurzlebigen zufälligen Zustand, eine nur am Callback gültige
HttpOnly-Transaktionscookie und eine weiterhin gültige ursprüngliche App-Sitzung.
Einmalige dauerhafte Ausführungsbelege verhindern die Wiederholung eines
unsicheren Codeaustauschs oder Token-Refreshs. Profilwechsel, Trennen, abgelaufene
Sitzungen und Revisionen werden vor Google-Anfragen erneut geprüft. Aktuelle
Konto-ID und Leseberechtigung bleiben am letzten Werkzeugübergang bindend.

Die einzigen festen Serverziele sind `gmail.googleapis.com` und
`oauth2.googleapis.com`; der Browser meldet sich an `accounts.google.com` an.
Serverseitige Netzwerkfreigabe bleibt erforderlich. HTTP-Weiterleitungen,
Umgebungs-Proxys, beliebige Accounts/URLs und automatische Wiederholungen sind
nicht vorgesehen. Produktive API- und Reverse-Proxy-Konfigurationen deaktivieren
Zugriffslogs; lokale OAuth-Betreiber müssen Callback-Code und Zustand ebenfalls
aus URL-Zugriffslogs heraushalten.

Lokal bestehen alle 1755 Tests, Ruff, mypy, Geheimnisprüfung, TypeScript und Build.
Die generische Integrations-Browserfolge einschließlich der Schreib-, Agenten-,
Proton- und neuen Gmail-Prüfungen besteht. OAuth- und Refresh-Grenzen sind
unabhängig geprüft. Neue vollständige CI und Auslieferung stehen noch aus.
Ein eigener realer
Google-OAuth-Client, die persönliche Anmeldung, echte Suche/Nachrichten und die
Mail-Abnahme in Chat/Aufgaben/Projekten stehen noch aus. Synthetische Prüfungen
und eine ausgelieferte Oberfläche ersetzen diese reale Kontoverbindung nicht.

Quellen: [Gmail OAuth](https://developers.google.com/workspace/gmail/api/auth/web-server),
[Scopes](https://developers.google.com/workspace/gmail/api/auth/scopes),
[Web-Server-OAuth](https://developers.google.com/identity/protocols/oauth2/web-server),
[Token-Laufzeiten](https://developers.google.com/identity/protocols/oauth2/),
[Persönliche Nutzung und Verifikation](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification).
Der offizielle [Gmail-MCP](https://developers.google.com/workspace/gmail/api/guides/configure-mcp-server)
ist derzeit Developer Preview mit eigener Programmteilnahme; diese Anbindung
verwendet deshalb die direkte Gmail API.
