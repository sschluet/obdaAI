# Systemberichte im Chat und als Aufgabenentwurf

Der lokale Router kann genau vier parametrierungsfreie Lesewerkzeuge auswählen:
Arbeitsraumstatus, HA-Status, HA-Backupmetadaten und HA-Wartungsplan. URLs,
Service-Aufrufe, Schreiboperationen und freie MCP-Namen sind ausgeschlossen.
Jeder Aufruf speichert einen dauerhaften ActionReceipt zum Chat-Lauf. Wiederholung
mit derselben Laufkennung liefert denselben Beleg, keine zweite Abfrage.

Nur die begrenzte Zusammenfassung gelangt als nicht vertrauenswürdiger LOCAL_ONLY-
Kontext zum lokalen Antwortmodell. Selbst bei Cloudfreigabe bleibt diese Antwort
lokal. Fehlender HA-Zugang erzeugt einen Fehler, keinen erfundenen Systembericht.

Der Aufgabenentwurf aus natürlicher Sprache wählt Titel und einen dieser festen
Berichtstypen oder lokale Analyse. Er speichert/aktiviert nichts. Der normale
Aufgabendialog dient der Prüfung, Terminwahl und anschließenden Aktivierung.
Das Modell vergibt keine Berechtigungen und bestimmt keine Zeitpläne.

Abnahme: Test weist Cloud-Unterdrückung, dauerhaften Beleg, Replay, begrenzten
Kontext und Ablehnung unbekannter Werkzeuge nach. Synthetische UI-Abnahme zeigt
den HA-Bericht im normalen Chat; keine produktive HA-Änderung.
