# Home-Assistant-Berichte als Aufgaben

Der normale Aufgabendialog bietet drei feste lesende Typen: Zustand/Updates,
Installation/Sicherungsmetadaten, Wartungsbericht. Termine, Wiederholungen und
bisherige Ergebnisse verwenden die vorhandene n8n-Zeitplanung und lokale Queue.
Kein JSON im Alltagsdialog. Berichte bleiben LOCAL_ONLY und enthalten weder Token
noch vollständige HA-Zustandsdaten.

TaskSpec bindet Werkzeugrevision, Aufgabenrevision und Kontrollrevision. Höchstens
ein HA-Bericht je Aufgabe; keine freie Entitätsauswahl, URL oder Aktionspayload.
Keine implizite Übergabe des Berichts an ein LLM. Doppelte Zustellung liefert den
gespeicherten Run ohne weitere Ausführung. Timeout/Fehler führen zu sichtbarem
Fehler; keine Wartungsänderung und kein Cloudfallback. Der Worker benötigt den
bereits vorhandenen HA-Zugang readonly gemountet; keine neuen HA-Dienstkonten.

Der Wartungsplan ordnet angebotene Versionswechsel ein, zeigt Backupmetadaten
und benennt Gesundheits-/Sicherungsprobleme. Ein Patchkandidat bedeutet lediglich
Versionsvergleich, keine sichere oder erlaubte Änderung. Metadatenflags dürfen
Archivintegrität, Wiederherstellungsschlüssel oder geprüften Restore nie ersetzen.
Ausführung bleibt gesperrt; ein GUI-Haken kann den Wiederherstellungsnachweis nicht
setzen. Produktive Updates, autonome Wartungsprofile und ein real getesteter
Wiederherstellungsweg sind weiterhin offen. Es existiert kein separater HA-Testserver;
Produktiv-HA wird gelesen, nicht zur destruktiven Restore-Abnahme verwendet.
