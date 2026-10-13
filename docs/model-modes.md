# Auto, Nur lokal und Cloud

Die Modellwahl bietet genau drei Optionen:

- **Auto:** vorhandene Routingregeln entscheiden zwischen lokal und freigegebener Cloud.
- **Nur lokal:** lokale Verarbeitung, ohne Cloud und ohne Websuche.
- **Cloud:** der konfigurierte externe Anbieter beantwortet die aktuelle Anfrage; die lokale Einordnung wird übersprungen.

Die Wahl bleibt im bestehenden Gespräch; es wird kein neues Gespräch und kein
zusätzlicher Anbieter-Freigabedialog geöffnet. Websuche ist in Auto und Cloud separat
umschaltbar. Die Einstellungen erlauben alle drei Modi als Browserstandard.

Cloud gilt für die aktuelle eingegebene oder bearbeitete/wiederholte Frage. Projekte,
Wissensquellen, ältere lokal geschützte Historie und nicht freigegebene Skills bleiben
lokal geschützt. Profilfelder werden nur gemäß ihrer eigenen Freigabe berücksichtigt.
Bei einer nicht erfüllten Cloudfreigabe, fehlendem Anbieter oder Budget liefert die
Anfrage einen sichtbaren Fehler; sie wird nicht stillschweigend lokal beantwortet.
Abgelehnte Eingaben und Bearbeitungen bleiben als Entwurf erhalten.

`model_cloud_only` ist ein optionales API-Feld für Nachricht, Wiederholung und
Bearbeitung. Der serverseitige Lauf-Snapshot bindet es an die tatsächliche Anfrage;
Routingbeleg und Vorschau zeigen den gewählten Modus. Vorhandene Clients ohne das
Feld behalten ihr bisheriges Routing. Es wird keine Datenbankmigration benötigt.

Die Grenze zur tatsächlichen Cloud wird mit synthetischen Provideradaptern geprüft.
Reale Cloud-Abnahme und überprüfter VM-Release sind in STATUS.md einzeln ausgewiesen.
