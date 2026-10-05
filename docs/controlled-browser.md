# Kontrollierte Browserprüfung

Unter Werkzeuge → Webseite prüfen werden feste, serverseitig freigegebene
öffentliche Seiten geprüft. Nutzer und Modelle können keinen beliebigen URL-,
JavaScript-, Formular- oder Browserbefehl eingeben. Ziel-ID und Konfigurationsdigest
sind an die Aktion gebunden. Produktion standardmäßig ohne Ziele (`{}`).

Die API ruft genau eine gepinnte öffentliche IPv4/HTTPS-Adresse mit festem Host und
TLS-SNI ab. Zertifikatsprüfung an, keine Redirects/Proxies/Cookies/Auth/Queryparameter.
Nur unverpacktes UTF-8-HTML bis 1 MB. Keine eigenen Dokumente oder Chats im Request.
Ein unveränderlicher Job enthält HTML und Digest; Neustart/Wiederholung verwendet
diesen Snapshot. Katalog-/Konfigurationsänderung verhindert neue Ausführung.

Chromium rendert den Snapshot in einem eigenen Container: non-root 10001,
`network_mode:none`, readonly Rootfs, keine Secrets/DB/Vault/Docker-Socket/Ports,
cap_drop ALL, no-new-privileges, begrenztes tmpfs/SHM, 768 MB RAM, ein CPU, 128 PIDs.
Chromium-Sandbox ist ausdrücklich aktiv. JavaScript, Serviceworker, Downloads,
WebSockets und weitere Ressourcen sind gesperrt; CSP default-src none. Pro Job ein
frisches Browserprofil, höchstens 35 Sekunden Prozesslaufzeit. Kein Profil-/Cookie-
Export. Das offizielle Seccomp-Profil wurde um genau `chroot` ergänzt: Chromium
benötigt dies innerhalb seines unprivilegierten User-Namespace. Kein Host-Capability
wird vergeben. Der unveränderte Profiltest scheiterte am Sandbox-chroot; die
gezielte Anpassung wurde getrennt mit aktiver Sandbox geprüft.

Ergebnis: maximal 64.000 Textzeichen und ein PNG der begrenzten 1280×720-Ansicht.
Dauerhafter ActionReceipt, geschützter authentifizierter Vorschau-Endpunkt und keine
automatische Übernahme in Modellkontext. Wiederholte Aktions-ID liefert denselben
Beleg. Resultate/Jobs sind private Laufzeitdaten und werden nicht versioniert.

Dies ist eine passive Seitenprüfung. Interaktiver Fallback für angemeldete Systeme,
geschützte Sitzungsspeicherung und sichere Login-/2FA-Übergabe sind noch offen;
keine Zugangsdaten im Chat anfordern oder automatisch eintragen. Fehlende Ziele
werden sichtbar angezeigt. Diese Grenzen sind keine vollständige Browserautomation.

Reproduzierbarer Runner: Playwright 1.62.1, pnpm-Lockfile, digest-gepinntes offizielles
Image. CI baut und testet echtes Chromium mit synthetischem HTML samt Script,
Metadata-Bild und Datei-Frame. Source-/API-Tests prüfen HTTPS/SSRF, Redirects, Limits,
Zieldrift, idempotente Belege und geschützte PNGs. UI-Fixture ist ausdrücklich
synthetisch; tatsächliche Isolation wird separat am Container geprüft.

Quellen für versionsabhängige Fähigkeiten:
- https://playwright.dev/docs/docker
- https://playwright.dev/docs/network
- https://playwright.dev/docs/api/class-browsercontext
- https://github.com/microsoft/playwright/blob/v1.62.1/utils/docker/seccomp_profile.json
