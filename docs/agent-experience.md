# Verständliche Anfrage- und Werkzeugausführung

## Ausgangspunkt und Entscheidung

Die Überarbeitung vom 25.11.2026 erweitert die vorhandene Chat-, Aufgaben- und
Agentenarchitektur. Es gibt keine zweite Chatoberfläche, Ausführungsdatenbank oder
neue Berechtigungsquelle. `Conversation`, `Message`, `Run`, `AgentJob` und
`AgentStep` bleiben die gespeicherten Originale.

| Bisheriger Befund | Konsequenz | Erweiterung |
| --- | --- | --- |
| Titel entstehen erst nach erfolgreicher gewöhnlicher Antwort; Agentchats fehlen | Auch fehlgeschlagene Gespräche heißen dauerhaft „Neues Gespräch“ | Sofortiger lokaler Basistitel, geschützte Nachbenennung alter Standardtitel |
| Fortschritt steckt im eingeklappten technischen Bereich | Lange Modell- oder Werkzeugschritte wirken wie Stillstand | Sichtbare Arbeitsphase im Gespräch und bei Aufgaben |
| Einordnung vor dem eigentlichen Auftrag hat keine erkennbare Aktivität | Die erste Wartezeit ist nicht verständlich | Unmittelbare, abbrechbare Einordnungsanzeige mit erhaltenem Entwurf |
| Administrationsläufe können dieselbe erfolgreiche Abfrage wiederholen | Leseschleifen verbrauchen Zeit und Kontext ohne Aktion | Beleggebundene Fortschrittsprüfung mit zulässigen frischen Nachprüfungen |
| Ein komplexes HTTP-Schema enthält Lesen, Schreiben und Verifikation | Kleine Modelle müssen viele technische Bedingungen zugleich erzeugen | Kleine schemaabgeleitete Lese-/Änderungsfassaden mit ursprünglicher Rückvalidierung |
| Ein verifizierter Effekt kann mit dem gesamten Ziel verwechselt werden | Ein Backup oder Teilupdate könnte als Fertigstellung erscheinen | Semantisch gebundene Zielzustände und belegte vollständige Kohorten |
| Abbrüche zeigen nur technische Sammelmeldungen | Gelesene Informationen und fehlende Schritte sind schwer erkennbar | Ehrliche Teilresultate, bestätigte Änderungen und klare Zustandsprüfung |
| Mobile Leisten und Bedienelemente beanspruchen viel Platz | Wenig Platz für Antwort und Fortschritt | Kompakte mobile Navigation, Integrationszeile und Ausführungsanzeige |

Als Referenz dienen die dokumentierten
[Ausführungsphasen und Fortschrittsereignisse von Hermes Agent](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/agent-loop.md)
und die [sichtbare Werkzeugaktivität der Desktopoberfläche](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/desktop.md).
Übernommen werden die Gestaltungsideen, keine fremde Laufzeit oder Policy.
Insbesondere gelten weiterhin die eigenen Grenzen für lokale Daten, Cloud,
Zielsysteme, Freigaben und unklare Effekte.

## Gesprächstitel

`titles.ensure_initial_title` erzeugt den ersten Titel ausschließlich lokal aus
der ersten aktiven Benutzernachricht. Das funktioniert bereits vor einer Antwort
und auch bei Modellausfall oder noch eingeplantem Agentenauftrag. Erkennbare
Zugangsdaten ergeben einen neutralen Titel statt einer Darstellung des Secrets.
Manuell gesetzte Titel gewinnen atomar, einschließlich eines absichtlich manuell
gewählten Titels „Neues Gespräch“.

Die vorhandene optionale lokale Verfeinerung bleibt erhalten. Ein Fehler dabei
entfernt den Basistitel nicht. Beim Laden werden alte geeignete Standardtitel
gebündelt aus der jeweils ersten Nachricht repariert. Verdeckte Modellgespräche,
manuelle Namen und archivierte Gespräche werden nicht umbenannt; ein früherer
Fehlerstatus führt zu keinem erneuten Modellauftrag. Es werden keine Historien
umgeschrieben oder an einen externen Anbieter übertragen.

## Sichtbarer Fortschritt

`agent_activity.activity` leitet eine kleine Darstellung aus echten Lauf- und
Schrittzuständen ab. Die API liefert sie als optionales `activity` im vorhandenen
AgentJob-Objekt. Die Anzeige unterscheidet Einplanung, Einordnung, Modellplanung,
Lesen, Recherche, Änderungen, Verifikation, interne Korrektur, Freigabe, Rückfrage
und Abschluss. Ein noch nicht gestarteter Schritt wird nicht als ausgeführt
beschrieben. Abbruchanforderung und bestätigter Abbruch bleiben unterscheidbar.

Die Zeitleiste enthält feste Beschriftungen und aufgezeichnete Statuswerte. Sie
übernimmt keine Modellgedanken, entfernten Texte, Shellausgaben oder Argumente.
Die Zähler beschreiben aufgezeichnete Schritte, keine vorhergesagte Restarbeit
oder Prozentwerte. Die kompakte Abfrage lädt dafür keine Belegkörper nach. Eine ausdrücklich
gewählte gewöhnliche Cloudanfrage ist nicht von einer lokalen Modelleinstufung
abhängig. Ein privater Systembezug und alle endgültigen Cloud-Datengrenzen bleiben
verbindlich.

Bei aktiven, wartenden, fehlgeschlagenen oder unklaren Aufträgen bleibt die
Aktivität auch bei geschlossenen „Details Abarbeitung“ sichtbar. Freigaben und
Rückfragen haben erreichbare nächste Aktionen. Nach einer erfolgreichen Antwort
gibt es keine zusätzliche Abschlusskarte: Die Antwort und genau eine kompakte,
standardmäßig geschlossene Detailszeile mit „Abgeschlossen“ beziehungsweise
„Abfrage abgeschlossen“ reichen als Rückmeldung. Terminale Hinweise
gehören zur passenden letzten Agentenantwort; sie bleiben nicht unter späteren
gewöhnlichen Antworten stehen. Bei Pollingfehlern zeigt die Oberfläche den letzten
bekannten Stand statt eines erfundenen Fortschritts.

Hintergrundaktualisierungen sind an Gespräch, aktiven Vordergrundlauf,
Befehlsrevision und die jüngste Detailabfrage gebunden. Ältere Antworten dürfen
weder ein fertiges Ergebnis noch einen eigenen Entwurf oder eine spätere
Umbenennung/Archivierung überschreiben. Während eines Vordergrundlaufs
zurückgestellte Aktualisierungen werden anschließend frisch abgefragt. Die
Detail-API liefert den tatsächlich gespeicherten Archivstatus.

„Zustand prüfen“ übermittelt einen kurzen lesenden Auftrag mit dem Verweis auf
den ursprünglichen unklaren Auftrag. Der Server bewahrt dessen vollständiges
Ziel und Effektbelege als private Daten, bindet ausschließlich ursprüngliche
weiterhin freigegebene Ziele und prüft ihre aktuellen Profil-/Policyrevisionen.
Weder zusätzliche Zielauswahl noch Recherche oder erneute Änderungen sind
zulässig. So muss ein langer ursprünglicher Auftrag nicht in den Folgetext
kopiert oder abgeschnitten werden.

Gewöhnliche Integrationsfragen benötigen keinen eigenen Modus. Der optionale
Expertenzugang „Systemauftrag“ liegt im Plus-Menü; bei Aktivierung erscheint ein
entfernbarer Hinweis auf die lokale Ausführung. Auto, Nur lokal und Cloud sowie
die Datenschutzgrenzen bleiben eigenständige Entscheidungen.

## Ausführung und Abschluss

Der gemeinsame Agent bleibt für Chat, Aufgaben und Projekte zuständig. Die
Anwendungsphase `Observe → Act → Verify` wird aus fehlenden Zielbelegen und
vorhandenen Absichten abgeleitet. Sie ist Planungshilfe und erteilt keine Rechte.
Schemafassaden ersetzen weder die kanonischen Werkzeuge noch deren abschließende
Argument-, Ziel-, Revisions- und Berechtigungsprüfung. Sie erzeugen keine
erratenen Endpunkte oder Verifikationswerte.

Auch anwendungseigene Inspektions- und Discovery-Beispiele werden für die native
Darstellung an die tatsächlich angebotenen Funktionen gebunden. Eine kanonische
HTTP-Projektion darf nicht als Beispiel für ein vereinfachtes Lesewerkzeug ohne
Projektionsparameter erscheinen. Übersetzbare Beispiele müssen den ursprünglichen
Aufruf verlustfrei darstellen; nicht übersetzbare Beispiele bleiben reine
Pfad-/Zweckhinweise. Gespeicherte Originale, private Definitionen und echte
abgerufene Daten werden dabei nicht umgeschrieben. Der JSON-Kompatibilitätsweg
behält seinen eigenen kanonischen Vertrag.

Der native Decoder akzeptiert neben bestehenden vollständig verpackten oder
unverpackten Argumenten eine eindeutig aufgeteilte Hülle: ausdrücklich angegebene
bekannte Parameter können nach der normalen äußeren Hülle einmalig mit dem
inneren Argumentobjekt zusammengeführt werden. Das ergänzt keine Werte und
akzeptiert keine unbekannten oder widersprüchlichen Parameter. Geschäftsfelder
mit den Namen `arguments` oder `parameters` werden nicht umgedeutet; Body und
Verifikationsdaten bleiben unverändert. Aktives Funktionsschema, ursprüngliches
kanonisches Schema und endgültige Zielrechte werden anschließend weiter geprüft.

### Modellaktive HTTP-Werkzeuge

`agent_http_facades` leitet für schemaabgedeckte HTTP-Fähigkeiten die angebotenen
Varianten `*_http_read`, `*_http_change` und `*_http_project` aus dem ursprünglichen
Vertrag ab. Lesen bindet GET und bietet weder Body noch Verifikation an. Änderungen
behalten die zugelassenen Methoden, Inhalte und unabhängigen Nachprüfungen. Die
flache Auswahl verwendet `items_path`, `fields`, `limit` sowie die ausdrücklich
gebundenen Felder `filter_mode`, `filter_field` und `filter_value`; eine verschachtelte
`projection`-Hülle gehört dort nicht zum Modellvertrag. `none` verlangt ein leeres
Filterfeld und JSON-null, `equals` erhält den JSON-Typ und `prefix` verlangt einen
String. Diese Aufteilung erteilt keine zusätzlichen Methoden, Pfade oder Rechte.

Die ersetzten kanonischen HTTP-Definitionen bleiben ausschließlich als private,
hashgebundene Metadaten für Rückvalidierung und Historienabgleich erhalten. Sie
werden nicht zusätzlich als aktive Funktionen an das Modell geschickt. Auch ein
bekannter, aber nicht angebotener versteckter Funktionsname wird bei einer neuen
Modellentscheidung abgelehnt. Die angebotenen Namen binden das konkrete Ziel;
Aliasargumente werden vor der bestehenden abschließenden Werkzeug- und
Berechtigungsprüfung wieder gegen dessen ursprüngliches Schema validiert.

Originalbelege und gespeicherte kanonische Argumente bleiben unverändert. Ein
Historieneintrag darf einen sichtbaren Alias nur erhalten, wenn dessen Schema
gültig ist und die Rückübersetzung nach kanonischer Normalisierung exakt denselben
Aufruf ergibt. Ein lediglich ähnlich aussehender Aufruf oder ein anderes Ziel
genügt nicht. Nicht verlustfrei darstellbare Historie wird nicht passend gemacht.

Ein wiederholter erfolgreicher Leseaufruf ohne Fortschritt wird intern behandelt.
Eine zwischenzeitliche Änderung am betroffenen Ziel erfordert weiterhin einen
frischen Beleg. Formatkorrekturen sind sowohl pro Episode ohne Fortschritt als
auch insgesamt begrenzt. Unklare oder unverifizierte Effekte werden nicht erneut
ausgeführt.

Optionale HTTP-Voraussetzungen gehören zur vorhandenen zielgebundenen
`Rules`-Revision (`effect_prerequisites`, standardmäßig leer). Eine Regel ordnet
einer konkreten HTTP-Operation eine zuvor im selben Auftrag und Ziel unabhängig
bestätigte Operation zu. Sie erteilt weder zusätzliche Methoden-/Pfadrechte noch
ein größeres Budget. Eine noch fehlende Voraussetzung wird der Planung mitgeteilt
und unmittelbar vor dem Versand erneut geprüft; unklare Effekte werden dadurch
nicht wiederholt. Selbstbezüge und zyklische Abhängigkeiten werden abgewiesen.
Die vorhandenen Regeln bestehender Ziele werden nicht automatisch erweitert.

Für Home Assistant kann im vorhandenen erweiterten Dialog optional „Sicherung
vor Updates“ gewählt werden. Das ist eine explizite Voraussetzung des Betreibers,
keine zusätzliche Rückfrage im Chat. Die Option fügt keine erforderlichen
HTTP-Rechte hinzu und ersetzt keine anderen konfigurierten Voraussetzungen.
Sie ist auch kein Nachweis, dass eine Sicherung wiederhergestellt werden kann.

Die neue HA-Vorgabe verwendet
[`backup.create_automatic`](https://www.home-assistant.io/actions/backup.create_automatic/)
mit den bereits in HA eingerichteten Sicherungseinstellungen. Vorhandene explizite
Regeln für [`backup.create`](https://www.home-assistant.io/actions/backup.create/)
werden nicht umgeschrieben; die offizielle Dokumentation verweist bei HA OS und
Supervised ausdrücklich auf die automatische Variante. Gleichwertige validierte
HTTP-/WebSocket-Aufrufe desselben HA-Dienstes werden nur für den Regelvergleich
zugeordnet; ihre ursprünglichen Argumente, Hashes und Transportrechte bleiben
maßgeblich. Direkte Supervisor- oder SSH-Aktualisierungen sind keine stillschweigend
gleichgesetzten Operationen dieser konkreten Dienstregel.

Der Abschluss muss den gesamten gebundenen Auftrag berücksichtigen. Bei
Entitätenzielen stammt eine anfängliche Zielkohorte aus einem vollständigen
Originalbeleg. Eine spätere kleinere Liste darf diese Kohorte nicht ersetzen.
Fehlende Zielentitäten, unbekannte Zielzustände, verbleibende Abweichungen oder
nicht passende Versionen sind kein Erfolg innerhalb dieser ausgewählten Kohorte.
Unbekannte oder nicht verfügbare Zustände außerhalb der Auswahl werden gesondert
benannt; sie werden weder als erledigt ausgegeben noch nachträglich in eine
bestätigte Auswahl umgedeutet. Eine belegte leere Auswahl ist von fehlenden oder
unvollständigen Anfangsbelegen zu unterscheiden. Ein Backup ist kein Beleg dafür,
dass ein Updateziel erreicht ist. Für beliebige Shellprogramme wird kein allgemeiner
formaler Erfolgsbeweis behauptet.

Ein interner Vertrag kann beispielsweise ein Updateziel als `effect_postcondition`
mit `outcome` beschreiben: Domäne `update`, gewünschter Zustand `off`,
`selection_state: on` und `attribute_from_initial: {installed_version: latest_version}`.
Die Auswahl stammt dann aus dem vollständigen Anfangsbestand; geprüft werden
anschließend dieselben Entitäten und die dort ursprünglich gemeldeten Zielversionen.
Dies ist ein interner semantischer Vertrag, keine JSON-Eingabepflicht für Benutzer.
Die reservierten Versionsattribute `installed_version` und `latest_version`
gehören in diesem Zielvertrag zur Domäne `update`. Das Ausgabeschema und die
Annahmeprüfung lehnen erfundene zusätzliche Versionsdomänen ab; andere
beobachtbare skalare Attributabbildungen bleiben möglich. Eine ungültige
Interpretation darf sich einmal innerhalb desselben gesamten Zeitbudgets lokal
korrigieren. Dabei werden nur feste Fehlercodes zurückgegeben, keine verworfenen
Modelltexte. Die erneute Interpretation durchläuft dieselben Anbieter- und
Eigentümerprüfungen; echte Teilaufgaben werden nicht stillschweigend entfernt.
Das Ausgabeschema bleibt dabei interne Formatsteuerung. Es wird nicht zusätzlich
als Teil des Benutzerprompts ausgegeben. Das begrenzte Ausgabetokenbudget für
die Einordnung muss auch am endgültigen Provideraufruf erhalten bleiben; die
adaptive Antwortlänge gewöhnlicher Chats ist davon unabhängig. API-Einordnung
und Hintergrundlauf verwenden denselben fachlichen Ausgabe- und Fehlervertrag.

Ein bereits belegter Zielzustand benötigt keinen künstlichen Änderungsschritt.
Bei einer fehlenden Bindung zwischen angefragten Entitäten und Änderungsziel wird
kein vollständiger Erfolg behauptet. Große abgeleitete Belegzusammenfassungen
werden kompakt dargestellt; Zielvertrag, Rechte und Originalbelege bleiben erhalten.

Bei einem Abbruch bleiben Status und ursprüngliche Fehlermeldung erhalten.
Belegte Teilresultate können ergänzt werden: beispielsweise erkannte Updates oder
die Anzahl bestätigter Änderungsschritte. Ein alter Zustandsbeleg vor einer
Änderung wird dafür nicht als aktueller Nachbeleg ausgegeben. Normale erfolgreiche
Antworten erhalten keine zusätzlichen technischen Fußtexte.

## Validierung und Grenzen

Unit-/API-Prüfungen behandeln Titel ohne Modell, alte Standardtitel, manuelles
Umbenennen, Modellwarteschlange, wechselnde Ausführungsphasen, authentifizierte
Fortschrittsabfragen, Teilresultate und unsichere Änderungen. Browserprüfungen
prüfen mobile Darstellung, sichtbare Aktivität, erhaltene Entwürfe, Abbruch während
der Einordnung, Rückfragen/Freigaben und die Zuordnung zu aktuellen Gesprächen.
Werkzeugtests prüfen außerdem gemischte Lese-/Änderungsabläufe, Verifikation,
Wiederholungen, Kohorten und Fehlzustände.

Diese synthetischen Fälle ersetzen keine reale Integrationsabnahme. Exakte
Gesamtläufe, installierte Releases, echte Modell-/Werkzeugprüfungen und offene
Abnahmen stehen in [STATUS](../STATUS.md). Erfolgreiche Lesetests sind kein Beleg
für eine tatsächlich durchgeführte HA-Aktualisierung oder Wiederherstellung.
