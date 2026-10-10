# Persönliches Profil

Unter **Einstellungen → Über mich** stehen freiwillige Felder für Name, gewünschte
Anrede, Beruf/Rolle, Familie/Lebenssituation, Herausforderungen, Ziele, Interessen
und weitere Hinweise. Es werden keine Informationen aus früheren Chats erraten
oder aus bestehenden privaten Quellen übernommen. Das Profil startet leer und
ausgeschaltet. Speichern und Aktivieren sind bewusst getrennte Entscheidungen im
Formular; der Aktivierungsschalter kann mit dem nächsten Speichern gesetzt werden.

Wenn das Profil aktiviert ist, erhalten lokale Chatantworten die ausgefüllten
Felder als persönlichen Hintergrund. Cloudantworten erhalten ausschließlich die
pro Feld ausdrücklich freigegebenen Angaben. Nicht freigegebene Felder werden
bei einer Cloudantwort ausgelassen; sie erzwingen allein keine lokale Auto-Route.
Das Profil erteilt weder Werkzeugrechte noch Web-, Dokument- oder Cloudfreigaben.
Private Angaben gelangen nicht automatisch in Suchtexte, Titel oder den Router.
Es beeinflusst aktuell Chatantworten; eine generelle Verwendung in Aufgaben oder
externen Aktionen wird nicht behauptet.

Der Server speichert das Profil lokal und revisionsgeschützt unter
`GET/PUT /api/personal-profile`. PUT bindet `revision`, `enabled`, `fields` und
`cloud_fields`; parallele Änderungen führen zu 409 und bewahren den UI-Entwurf.
Die ersten vier Felder erlauben jeweils 200 Zeichen, die übrigen jeweils 2.000,
insgesamt höchstens 8.000. Cloud-Feldnamen sind fest typisiert; unbekannte Felder,
doppelte Freigaben und zusätzliche Rechte sind ungültig.

Jeder neue Lauf friert Profilrevision, aktivierten Inhalt, Freigaben und SHA-256 separat ein.
Bei ausgeschaltetem Profil bleiben die gespeicherten Angaben im Profil, werden aber
nicht als ungenutzte Kopie in neue Laufverläufe übernommen.
Erst nach der tatsächlichen Anbieterwahl wird passender Profilkontext ergänzt.
Cloudgrants binden ausschließlich die explizit freigegebene Teilmenge an den
gewählten Anbieter und die eingefrorene Revision. Lokal profilgestützte Antworten bleiben LOCAL_ONLY, sobald ein verwendetes
Profilfeld oder ein anderer Kontextteil nicht für Cloud freigegeben ist. Sind
alle verwendeten Angaben freigegeben, dürfen ihre erlaubten Ableitungen in einem
freigegebenen Auto-Gespräch später ebenfalls Cloudkontext sein. „Nur lokal“ hat
weiterhin Vorrang. Die Routing-Erklärung enthält
nur Revision und angewendete/ausgelassene Feldnamen, keine persönlichen Werte.
Kontext-, Ausgabe- und Kostenlimits bleiben wirksam.

Entwürfe bleiben beim Wechsel zwischen Einstellungstabs erhalten. Navigation aus
den Einstellungen, Verlaufnavigation und Schließen des Browsers schützen
ungespeicherte Eingaben. **Profil leeren** leert die aktuellen Felder und Freigaben
und schaltet das Profil nach Bestätigung aus. Bestehende Chatantworten und frühere
Lauf-Snapshots werden dadurch nicht gelöscht. Entwürfe werden nicht in Browser-
Storage geschrieben. Migration 0030 ergänzt ein leeres Profil und verweigert einen
Downgrade, solange konfigurierte Daten dadurch verloren gingen.

API-, Kontext-, Cloud-, Titel-/Web-Abgrenzungs- und Browserprüfungen verwenden nur
synthetische Angaben. Releasegebundene CI-/VM-Belege stehen in STATUS.
