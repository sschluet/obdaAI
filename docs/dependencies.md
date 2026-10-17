# Abhängigkeiten und offizielle Grundlagen

Stand 04.10.2026. Exakte Paketversionen aus PyPI/npm geprüft, transitive Auflösung
in uv.lock/frontend/pnpm-lock.yaml. Python 3.12 und Node 24 LTS als reproduzierbare Basis.
Versionen sind bewusst gepinnt, Updates separat mit Tests.

| Komponente | Aufgabe | Lizenz / offizielle Quelle |
|---|---|---|
| React / Vite / TypeScript | statische UI, Build, Typprüfung | MIT / MIT / Apache-2.0; https://vite.dev/guide/ |
| FastAPI / Pydantic | API und validierte Verträge | MIT; https://fastapi.tiangolo.com/deployment/versions/ |
| SQLAlchemy / Alembic | DB und Migration | MIT; https://docs.sqlalchemy.org/ ; https://alembic.sqlalchemy.org/ |
| psycopg | PostgreSQL-Protokoll | LGPL-3.0; https://www.psycopg.org/psycopg3/docs/ |
| Paramiko 4.0.0 | explizit gebundene SSH-/SFTP-Verbindungen, kein Shell-Dispatcher | LGPL-2.1; https://docs.paramiko.org/en/stable/api/sftp.html ; https://github.com/paramiko/paramiko/blob/4.0.0/LICENSE |
| Procrastinate 3.10.0 | persistente App-Queue auf PostgreSQL | MIT; https://procrastinate.readthedocs.io/en/stable/discussions.html |
| PostgreSQL | App-Daten, getrennte n8n-DB | PostgreSQL License; https://www.postgresql.org/docs/ |
| n8n (bestehende Instanz) | Zeitpläne und Workflows | Sustainable Use License, kein pauschales OSI-Open-Source-Versprechen |

n8n-Community/API/Lizenzfunktionen vor Integration anhand vorhandener Version und
offizieller Referenz erneut prüfen. Kein unbewiesenes Feature in V1 versprechen.
Word/PPTX/PDF/Bild-/OCR-/Browserbibliotheken und LibreOffice erst für M2/M4 auswählen,
mit ihren tatsächlichen Grenzen dokumentieren. Kein Runner im privilegierten API-Prozess.

## Nachgewiesene n8n-Grundlagen
Vorhandene Version 2.7.5: offizielle versionierte OpenAPI-Referenz
https://github.com/n8n-io/n8n/blob/n8n%402.7.5/packages/cli/src/public-api/v1/openapi.yml
und Lizenz https://github.com/n8n-io/n8n/blob/n8n%402.7.5/LICENSE.md .
Public-API-Authentifizierung verwendet X-N8N-API-KEY; vorhandener Zugang und
freigeschaltete Funktionen sind noch nicht live geprüft. Persönliche interne Nutzung
ist im Lizenzrahmen vorgesehen; kein Hosting fremder Kundencredentials geplant.

HTTPX-IP-Pinning verwendet die dokumentierte sni_hostname-Extension, Host bleibt
der ursprüngliche Name und TLS-Prüfung bleibt aktiv: https://www.python-httpx.org/advanced/extensions/ .
Alle DNS-Antworten prüfen, dann direkt zur geprüften IP verbinden; keine zweite
DNS-Auflösung und keine Redirects/Umgebungsproxies.

CI: ubuntu-24.04 statt wechselndem ubuntu-latest; offizielle Actions-Releases
checkout v7.0.1 / setup-python v7.0.0 / setup-node v7.0.0 anhand GitHub Releases
und Tag-Commitobjekten geprüft und auf Commit-SHAs gepinnt. PR-Prüfungen und
main-Pushes laufen; doppelte Branch-Push-/PR-Prüfungen werden vermieden.

HA-Backup-Leseadapter: websockets 17.1, BSD-3-Clause, gepinnt mit Lock/Hashes.
Offizielle Herkunft https://pypi.org/project/websockets/17.1/ und API
https://websockets.readthedocs.io/en/stable/reference/sync/client.html .
Kein generischer WebSocketzugang; fester Host, geprüfter Socket, minimale Kommandos.

Office-Dateirunner: LibreOffice Writer, Impress und Calc erstellen lokale PDF-/PNG-
Vorschauen für DOCX, PPTX und XLSX. Calc ergänzt die bestehende isolierte Runtime;
keine Office-Makros oder importierten Skillskripte werden ausgeführt.
