# Dateifolgeversionen im Projektchat

Eine konkrete Änderungsbitte wie „Überarbeite die letzte Word-Datei“ oder
„Kürze Folie 2 der letzten PowerPoint“ bindet die letzte erfolgreich verknüpfte
Datei dieses Gesprächs. Die Änderung muss die letzte Datei ausdrücklich benennen;
ein alleinstehender numerischer Folienbefehl ist ebenfalls zulässig. Ein anders
benanntes oder unklar bezeichnetes Dokument wird nicht automatisch durch die
letzte Datei ersetzt. Direkte unklare Dateiänderungsaufträge werden bereits vor
der Modellklassifikation mit einer konkreten Auswahlmeldung abgewiesen. Es werden höchstens 50 vergangene erfolgreiche Runs
geprüft. Andere Gespräche, beliebige Projektdateien und vom Modell gelieferte IDs
sind keine Auswahlquelle. Fehlt eine eindeutige aktuelle Ausgangsversion, wird
nichts erstellt; die konkrete Version kann im normalen Dateidialog gewählt werden.

Die Ausgangsversion muss weiterhin die aktuelle Version genau dieses Artefakts
sein. Format und vollständige Quellrevisionen/Hashes bleiben erhalten. Neue oder
ersetzte Quellen brauchen eine ausdrückliche Auswahl im Dateidialog. Das lokale
Modell erhält den gebundenen Datenplan und dieselben begrenzten Quellen wie ein
normaler Folgeentwurf; keine zusätzlichen Gesprächs-, Projekt- oder Vaultinhalte.

Ein eindeutig numerisch bezeichnetes Folienziel muss innerhalb der vorhandenen
Folienzahl liegen. Anzahl, Präsentationstitel und alle anderen Folien einschließlich
Notizen bleiben exakt gleich, sonst wird der Modellplan vor Dispatch abgewiesen.
Eine einzelne quellengebundene Folie benötigt aktuell den Dateidialog; die globale
Quellenreferenz würde sonst auch die Notizen anderer Folien verändern. Ganze
quellengebundene Word-/PowerPoint-Entwürfe können als Folgeversion geplant werden.

Nur der exakt früher serverseitig angehängte Quellenblock wird aus dem als Kontext
verwendeten Plan herausgenommen und für die neue Version neu aufgebaut. Nutzertext
oder Notizen mit ähnlicher Überschrift werden erhalten. Es gibt keinen allgemeinen
Textfilter und keine Veränderung der gespeicherten Ausgangsvorgabe.

Modellvorschlag/Token binden Ausgangs-ID, Revision, Vorgabenhash, Quelle, Provider
und Projekt. Der letzte Schreibpunkt prüft zusätzlich neue Nutzerfrage, aktive
Nachrichtrevision/SHA, Gespräch, Run und Abbruchzustand. Folgeversion und Queue
werden über denselben Artefaktdienst gemeinsam gespeichert. Die alte Ausgabe wird
nicht überschrieben. Eine neue Version benötigt erneut Vorschauprüfung vor Download.
