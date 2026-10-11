# Lange Konzepte und Antwortgrenzen

Ein Modell kann eine Antwort am Ausgabelimit beenden, obwohl bereits brauchbarer
Text vorliegt. Das ist von einem Verbindungsfehler oder einer Inhaltsfilterung zu
unterscheiden. Die empfangene Teilantwort, ihre Modellherkunft und die Laufhistorie
bleiben gespeichert. Ein erreichtes Ausgabelimit mit vorhandenem Text erhält den
terminalen Status `limited` und einen Hinweis statt eines fehlgeschlagenen Laufs.
Ohne empfangenen Antworttext bleibt es ein Fehler; Providerfilter werden weiterhin
als eigenständiger Abbruch behandelt.

## Antwortumfang

Die gewünschte maximale Antwortlänge wird in der Modellverbindung eingestellt
und kann bis zu 8192
Tokens betragen. Für die konkrete Anfrage begrenzen die verbleibende
Kontextkapazität, aktuelle Modellpreise und bestehende Cloudbudgets den tatsächlich
verfügbaren Umfang. Ein Token ist keine feste Wort- oder Zeichenanzahl.

Die Anwendung erhöht weder das Kostenlimit pro Lauf noch das Monatsbudget
automatisch. Am11.10.2026 hat der Nutzer für die Test-VM ausdrücklich0,05USD
pro Cloudanfrage und1USD im Monat freigegeben. Das Antwortlimit einer Modellverbindung bleibt eine konfigurierbare
Grundlage; die Reservierung verwendet den tatsächlich für diesen Lauf freigegebenen
Umfang. Unter **Einstellungen → Modelle** lassen sich Modellverbindungen,
Antwortgrenzen und Kostenlimits prüfen. **Einstellungen → Routing** erklärt die
Modellauswahl; eine andere Routingstrategie erhöht keine Budgets.

## Bewusst fortsetzen

Bei einer erhaltenen Antwort am Ausgabelimit bietet der Chat eine manuelle
Fortsetzung an. Sie erzeugt eine neue normale Chatnachricht mit eigenem Lauf und
eigener Kostenprüfung. Sie überschreibt die Teilantwort nicht und beginnt nicht
automatisch im Hintergrund. Die aktuelle Modellwahl und die normalen
Datenschutzgrenzen gelten weiterhin: „Nur lokal“, private Projektquellen und
frühere lokale Inhalte erhalten dadurch keine Cloudfreigabe. Ist ein Cloudlauf
wegen Budget oder Kontext gesperrt, bleibt diese Grenze sichtbar.

Eine Fortsetzung ist keine Garantie für einen nahtlosen oder vollständig
redundanzfreien Text. Für sehr umfangreiche Konzepte können klar benannte Kapitel
in getrennten Anfragen hilfreich sein. Zeitlimits, Kontextlimits, Providerfilter
und Netzwerkfehler bleiben eigene Fehlerursachen und werden nicht als erfolgreich
abgeschlossene Antwort ausgewiesen.

Die öffentliche Galerie verwendet ausschließlich synthetische Beispieltexte und
simulierte Laufmetadaten. Sie belegt die Oberfläche, nicht einen echten
Provideraufruf oder die Live-Abnahme einer bestimmten Modellkonfiguration.
