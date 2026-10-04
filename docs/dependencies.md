# Abhängigkeiten und offizielle Grundlagen

Stand 04.10.2026. Exakte Paketversionen aus PyPI/npm geprüft, transitive Auflösung
in uv.lock/package-lock.json. Python 3.12 und Node 24 LTS als reproduzierbare Basis.
Versionen sind bewusst gepinnt, Updates separat mit Tests.

| Komponente | Aufgabe | Lizenz / offizielle Quelle |
|---|---|---|
| React / Vite / TypeScript | statische UI, Build, Typprüfung | MIT / MIT / Apache-2.0; https://vite.dev/guide/ |
| FastAPI / Pydantic | API und validierte Verträge | MIT; https://fastapi.tiangolo.com/deployment/versions/ |
| SQLAlchemy / Alembic | DB und Migration | MIT; https://docs.sqlalchemy.org/ ; https://alembic.sqlalchemy.org/ |
| psycopg | PostgreSQL-Protokoll | LGPL-3.0; https://www.psycopg.org/psycopg3/docs/ |
| Procrastinate (ab Worker-Einführung) | persistente App-Queue auf PostgreSQL | MIT; https://procrastinate.readthedocs.io/en/stable/discussions.html |
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
