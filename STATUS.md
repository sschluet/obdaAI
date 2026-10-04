# Status — 04.10.2026

M0 lokal in Arbeit. Keine vollständige Version 1, kein produktives Deployment.

## Umgesetzt
Autorisierte lesende Bestandsaufnahme; eigenständige Projektstruktur; Architektur,
Daten-/Sicherheitsmodell, vollständiger Meilenstein-/Abnahmeplan; ausführbare API-
Healthroute und validierte Routing-/Privacy-Verträge; synthetische Negativtests;
CI-Grundlage und lokaler Source-Secret-Scan. Keine bestehenden Dienste geändert.

## Blockiert / noch nicht geprüft
- GitHub-CLI HTTP 401, Owner nach Browser-Reauth prüfen. Lokale Commits werden als Codex (codex@localhost) gekennzeichnet, nicht als Benutzercommit. Kein privates
  Remote-Repository, kein Push oder PR behauptet.
- Neue Ziel-VM und Provisionierungsfreigabe offen. Vorhandene Proxmox-Rechte sind
  nicht automatisch für neue IDs gültig.
- Vorhandene n8n-API-Authentifizierung, Workflow-/Credential-Inventar und kontrollierte
  Migration auf Linux fehlen; keine zweite Instanz anlegen.
- Login/Chat/UI, Worker, Providerintegration und M2-M5 noch offen.
- 10 Foundation-Tests bestanden; Ruff und strikte Mypy-Prüfung bestanden. Paketbuild läuft; M0 ist extern durch GitHub-Auth blockiert.

## Präziser Fortsetzungspunkt
M0 Lockfiles/Tests/Build fertigstellen; nach Auth Owner/Privacy bestätigen, M0 committen,
pushen und PR erstellen. Danach M1 mit Login/DB-Migration, finalem Egress-Gateway,
lokalem Router und persistenter Streaming-UI. Keine echte Cloudanfrage ohne enge Freigabe.
