# Projekträume, Aufgabenübersicht und Wissensquellen

Projekte beginnen mit einer Übersicht eigener Räume. Jeder Raum hat die Reiter
Gespräche, Quellen und erstellte Dateien. Neue und fortgesetzte Gespräche sind an
genau diesen Raum gebunden. Dateien sowie explizit ausgewählte öffentliche
HTTPS-Seiten werden lokal als unveränderte Momentaufnahmen gespeichert, gehasht,
eingelesen und mit Fundstellen für den normalen Projektchat bereitgestellt.
Webseitenabrufe senden keine anderen Quellen, folgen keinen Weiterleitungen und
weisen private/Loopback-/Metadatenadressen, Anmeldedaten und gemischte DNS-Ziele ab.
Der ausdrücklich vom Besitzer gewählte Webseitenabruf ist vom modellgesteuerten
Webzugriff getrennt; letzterer behält seine vorhandene Domainfreigabe.

Aufgaben starten in einer separaten Übersicht mit Status, Ausführung, nächstem
Termin und vorhandenen Ergebnissen. Bestehende Aufgaben öffnen eine Detailansicht;
Erstellen/Bearbeiten ist ein eigener Dialog. Zwei idempotente Beispiele bleiben
initial pausiert: Arbeitsraumüberblick sowie tägliche lokale Kurzfassung um 09:00
Europe/Berlin. Eigentümeränderungen werden beim erneuten Laden nicht überschrieben.
Zeitpläne, Freigaben und Ausführungshistorie behalten ihre bestehenden Grenzen.

Modellwahl und Quellenoptionen sitzen direkt in der Chateingabe. Auto/lokal und
freigegebene Cloudanbieter ersetzen die verstreuten Auswahlen. Ein Anbieterwechsel
öffnet nach konkreter Zustimmung ein neues Gespräch; private Altinhalte werden
nicht implizit neu freigegeben. Projekt-/Wissensquellen bleiben lokal. Öffentliche
Websuche bestätigt den exakten aktuellen Nachrichtentext; Bearbeitung invalidiert
die Freigabe. Die Quellenoption ist im strikt lokalen Modus deaktiviert.

Wissen startet mit Quellenkarten. Der vorhandene Obsidian-Vault bleibt erhalten;
die gezielte Merkliste ist ein eigener Reiter. Zusätzliche SMB-/Obsidian-, NFS- und
PostgreSQL-Verbindungen sind im Dialog frei konfigurierbar: Server, Freigabe/Ordner
oder Datenbank/Schema/Tabelle, Benutzer, verschlüsselte Zugangsdaten und Grenzen.
Keine UI-Adresse wird zu einem Shellbefehl oder freien SQL-Statement.

SMB verwendet eigene Verbindungscaches je Quelle, SMB3-Verschlüsselung, Signierung,
keine DFS-Verweise und ausschließlich lesende Dateiöffnungen. NFS verwendet nur
feste libnfs-Lesebinaries in privaten Netzen, ohne Kernel-/FUSE-Mounts oder zusätzliche
Capabilities. PostgreSQL bindet eine konkrete IP, feste gequotete Identifikatoren,
Readonly-Transaktion, Statementtimeout und begrenzte Datenmomentaufnahmen; öffentliche
SQL-Endpunkte erfordern TLS. Schreibmethoden sind nicht Teil der Adapter.
Bibliotheksreferenzen: [SMB-Client](https://github.com/jborean93/smbprotocol) und
[libnfs](https://github.com/sahlberg/libnfs).

Indexierung läuft dauerhaft in der Source-Queue. Jede Abgleichgeneration hat eine
neue Revision; veraltete Zustellungen können sie nicht fortsetzen. Dokumente werden
lokal in einem separaten internen Wissensraum eingelesen. Dieser erscheint nicht in
der normalen Projektliste und wird nicht automatisch in andere Gespräche gemischt.
Gleiche Inhalts-SHAs erzeugen keine neue Kopie; geänderte Inhalte oder Zielbindungen
stellen alte Treffer zurück, ohne Originale zu überschreiben. Pausieren sperrt neue
Wissenschats. Zugangsdaten werden mit dem vorhandenen Masterkey und einem separaten
Knowledge-AAD verschlüsselt, nie in Modelldaten oder Antwort-/Validierungslogs ausgegeben.

Grenzen: initiale Snapshotgrenzen, Dokumentanzahl, Dateigröße und Gesamtspool bleiben
begrenzt und sichtbar. Indexierung ist lokale Fundstellenretrieval, kein behaupteter
semantischer Vektorindex. Echte individuelle NAS-/NFS-/SQL-Anbindungen benötigen vom
Besitzer eingetragene Ziele und dort erlaubte lesende Zugriffe; ohne konkrete Quelle
wird keine reale Verbindung als abgenommen bezeichnet. Bestehende Shares,
Vaultsync, Home Assistant und n8n werden nicht umkonfiguriert.

Die ausdrücklich genehmigte Quellen-Netzwerkfreigabe ergänzt eine eigene
OBDAAI_SOURCES-Kette vor den unveränderten bisherigen App-Regeln. Nur authentifizierte
manuelle Quellenaktionen beantragen fünf Minuten gültige Freigaben für aufgelöste
numerische Zieladressen und das gewählte Protokoll. Öffentliche Webseiten erhalten
ausschließlich HTTPS/443; interne HTTP-, Loopback- und Metadatenziele bleiben gesperrt.
NFS erlaubt private Ziele mit 111/2049 und dem dort ermittelten MOUNT-v3-Port.
Der eigene Root-Dienst bestätigt erst nach Anwendung der Regeln; bei Fehler oder
Dienststopp leert er nur seine eigene Kette. Modellwerkzeuge können keine Freigaben
beantragen. Die Freigabe aktiviert weder Cloudübertragung noch weitere Ziele.
