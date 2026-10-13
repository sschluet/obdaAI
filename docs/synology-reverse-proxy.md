# HTTPS-Zugang über Synology

Die Synology wird vom Benutzer eingerichtet. Die VM bietet dafür einen getrennten
HTTPS-Host neben dem bestehenden IP-Zugang. Die App-Version und Datenbank ändern
sich dadurch nicht. Es werden keine zusätzlichen öffentlichen VM-Ports geöffnet.

## DSM-Regel

Unter **Systemsteuerung → Anmeldeportal → Erweitert → Reverse Proxy**:

| Einstellung | Wert |
| --- | --- |
| Quelle | HTTPS, gewünschter Domainname, Port443 |
| Ziel | HTTPS, private IP der Test-VM, Port443 |
| Request-Header Host | Gewünschter Domainname; nicht auf die VM-IP umschreiben |
| HTTP-Version zum Ziel | HTTP1.1 |
| Lesezeitlimit | 600 Sekunden |
| Antwortpufferung / Cache | Deaktiviert, soweit im DSM verfügbar |

Das öffentliche Zertifikat muss auf der Synology dem Domain-Host zugeordnet sein.
DNS und die externe Weiterleitung führen auf die Synology, nicht direkt auf die VM.
Der Backend-TLS-Endpunkt verwendet das bestehende private VM-Zertifikat; bei
aktivierter Zertifikatsprüfung muss der Proxy diesem Zertifikat vertrauen.
Chatantworten verwenden Server-Sent Events. Dafür ist keine WebSocket-Umstellung
nötig; Pufferung und zu kurze Lesezeitlimits dürfen den Stream nicht unterbrechen.

## VM-Konfiguration

`deploy/nginx-synology.conf.template` wird mit dem exakten Domainnamen, VM-IP und
NAS-IP befüllt und zusätzlich zum unveränderten privaten IP-vHost installiert.
Nur die NAS-IP und VM-interne Diagnose dürfen den Domain-vHost erreichen. Der
bestehende private IP-Zugang bleibt erhalten; keine Firewalländerung nötig, wenn
die NAS bereits zur privaten HTTPS-Freigabe gehört.

Eine **exakte** Origin-Abbildung am VM-Proxy übersetzt ausschließlich den
freigegebenen HTTPS-Domain-Origin zum bestehenden internen App-Origin. Fremde,
fehlende oder abweichende Origins bleiben unverändert und werden weiterhin von
der App abgewiesen. Eine pauschale feste Origin-Kopfzeile am Synology-Proxy würde
diesen Schutz umgehen und darf nicht konfiguriert werden. CSRF-Token und sichere,
HttpOnly-/SameSite-Strict-Cookies bleiben erforderlich. Der neue vHost aktiviert
weder CORS-Freigaben noch eine Weiterleitung beliebiger Hosts.

Vor Installation: bestehende Nginx-/HTTPS-Konfiguration sichern, aktiven Release
prüfen, Datei atomar installieren und `nginx -t` ausführen. Reload nur nach
bestandener Prüfung. Bei fehlgeschlagener Abnahme ausschließlich den neuen Host
entfernen beziehungsweise dessen vorherige Fassung wiederherstellen. Der Rollout
von App-Images muss diesen Host erhalten; bestehende Compose-Overlays bleiben
unverändert. Der End-to-End-Zugang hängt von der vom Nutzer eingerichteten
Synology-Regel sowie DNS und externem Routing ab.
