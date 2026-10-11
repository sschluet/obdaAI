# Gezielte CI statt vollständiger App-Tests für jedes Textupdate

Das App-Repository obdaAI ist öffentlich. Website und App bleiben im selben
Repository; Pages veröffentlicht nur den eigenen gh-pages-Branch.

## Prüfklassen

| Änderung | Prüfung |
| --- | --- |
| Backend, Frontend, Tests, Abhängigkeiten, Images, Laufzeit-/Build-/App-CI-Konfiguration | Vollständige App-Suite, solange kein identischer vollständig geprüfter App-Baum nachgewiesen ist |
| README, STATUS, AGENTS und docs/ | Kleine CI-Logikprüfung, Source-Scan und eigenständige Geheimnisprüfung; bestehender App-Nachweis wird wiederverwendet |
| website/, Showcase-Build/Publisher/Browsercheck oder Website-Workflow | Website-Allowlist und Website-Browsercheck; App-Suite nur bei zugleich geänderter App |
| Unbekannte Dateien, fehlender/abgelaufener Nachweis oder API-Fehler | Vollständige App-Prüfung |
| Manueller workflow_dispatch der App-CI | Vollständige App-Prüfung unabhängig vom Cache |

`frontend/package.json` und Lockfiles sind App-relevant und beeinflussen zusätzlich
die Website-Prüfung. Unbekannte Markdown-Dateien werden nicht pauschal ausgeschlossen:
Skill-Anweisungen oder Runtime-Inhalte können funktionale Eingaben sein.

## Sicherer Nachweis des geprüften Codes

GitHub-PR-Pfadfilter beziehen sich auf die gesamte Änderung seit PR-Beginn.
Ein reines Textupdate an einem bestehenden Code-PR würde damit erneut alles starten.
Stattdessen berechnet scripts/ci_changes.py eine SHA256-Signatur aller relevanten
getrackten Pfade, Dateimodi und Git-Blobs des tatsächlich ausgecheckten Baums.
Auch App-CI-Workflow und Klassifikator gehören zu diesem Baum.

Nur nach sechs erfolgreichen vollständigen Prüfjobs wird ein kleines
app-check-proof-Artifact erzeugt: tatsächlicher Checkout-SHA, Baum-Signatur,
Repository und ursprünglicher Run. PR-Checkout kann ein Merge-Commit sein; der
Nachweis verwendet daher nicht einfach den PR-Head-SHA. Wiederverwendende Läufe
geben den ursprünglichen Nachweis an und erzeugen keinen neuen Vollprüfnachweis.

Die Wiederverwendung prüft den ursprünglichen Run erneut: gleiche Repository-
Herkunft, richtige Workflowdatei, completed/success und alle sechs Jobs tatsächlich
success. Abgebrochene, teilweise ausgeführte oder Fork-Läufe gelten nicht als
vollständiger Nachweis. Artefakte bleiben90 Tage erhalten; ohne passenden Nachweis
wird vollständig geprüft. Die API erhält nur Leserechte; signierte Storage-
Downloads erhalten keinen GitHub-Authorization-Header.

Wenn ein Dokumentationspush einen laufenden Code-Lauf abbricht, fehlt noch dessen
gültiger Nachweis. Der neue Lauf prüft diese noch ungeprüfte App deshalb vollständig.
Ein neuer Text-Commit kann keinen ungeprüften Code als erfolgreich ausgeben.

## Weniger parallel laufende Arbeit

App- und Website-Workflow besitzen je eine Gruppe aus Workflowname und Git-Ref
mit cancel-in-progress:true. Neue Pushes ersetzen überholte Läufe desselben PRs
oder Branches; unabhängige Branches werden nicht gegenseitig abgebrochen.

Der Website-Workflow startet nur für relevante öffentliche Dateien, die eigenen
Build-/Prüfskripte und deren Abhängigkeiten. Der früher ungenutzte große Pages-
Artifact-Upload entfällt: Der Publisher erstellt den geprüften Build selbst und
pusht nur gh-pages. Reine Dokumentationsupdates erfordern keine erneute Website-
Veröffentlichung, wenn die öffentliche Darstellung unverändert bleibt.

Kleine zusammengehörige Änderungen werden lokal gesammelt, geprüft und gemeinsam
gepusht. Ein nachträglicher Bericht mit erst später verfügbaren CI-/Deployment-
Belegen kann als gebündeltes Dokumentationsupdate folgen; er startet bei identischem
geprüftem App-Baum keine neue schwere App-Suite. Abgebrochene Läufe und wiederverwendete
Nachweise sind im Abschlussbericht von tatsächlich neu ausgeführten Tests zu trennen.
