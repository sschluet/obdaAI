# Weitere Dienste: geeignete Anschlusswege

Recherche: **11.10.2026**. Status: **Recherche und technische Empfehlung; die hier beschriebenen zusätzlichen Connectoren sind nicht implementiert und nicht an realen Konten getestet.** Grundlage sind ausschließlich offizielle Anbieterquellen. „Keine bestätigte öffentliche API“ beschreibt den Recherchebefund, nicht den Beweis, dass keinerlei interne oder vertraglich verfügbare Schnittstelle existiert.

| Dienst | Geeigneter Anschlussweg | Anmeldung / Voraussetzung | Empfehlung für obdaAI |
| --- | --- | --- | --- |
| Proton Mail | Lokal laufende Proton Mail Bridge mit IMAP | Bezahlter Proton-Mail-Tarif; separate Bridge-Zugangsdaten | Späterer lokaler Mail-Connector, zunächst nur lesen; kein erfundener API-Key-Zugang |
| Gmail | Offizielle Gmail API | OAuth 2.0, zunächst `gmail.readonly` | Eigener OAuth-Connector; Benutzer wählt Labels, Zeitraum und Anhänge |
| immocloud | Manuelle Excel-/CSV-/DATEV-/Dokumentexporte | Export im Kundenkonto | Importprofil mit wiederholbarer Spaltenzuordnung und Auswertungs-Use-Case |
| Synology | SMB für Dokumente; File Station API für Dateifunktionen | NAS-Benutzer und gezielte Ordnerrechte; DSM-Sessionauth für API | Wissensquelle und Verbindungsprofil verknüpfen; DSM-Steuerung getrennt behandeln |
| Amazon Privatkonto | Selbst heruntergeladene Daten, Rechnungen und Bestellunterlagen | Anmeldung beim Anbieter; keine bestätigte allgemeine Privatkonto-API | Importprofil; keinen universellen Live-Connector versprechen |
| Amazon Business | Offizielle Business Reporting API | Freigabe/Onboarding durch Amazon, passende Rolle und Tokens | Optionaler eigener Business-Connector nach Zugangsklärung |
| Amazon Verkäufer/Vendor | Selling Partner API (SP-API) | Entwicklerregistrierung, Rollen und OAuth bzw. Selbstautorisierung | Separater Händler-Connector; nicht für private Käuferbestellungen verwenden |
| CHECK24 | Selbst bereitgestellte Vertrags-/Angebotsdokumente und Anbieter-Mails | Kundenkonto; API-Zugang für Privatkonten nicht bestätigt | Dokument-/Mailimport mit Herkunft; Partner-API nur mit passendem Vertrag |

## Proton Mail

Proton dokumentiert Bridge als lokale IMAP-/SMTP-Brücke für macOS, Windows und Linux, verfügbar mit bezahltem Mail-Tarif. Bridge entschlüsselt Nachrichten auf dem Rechner. POP3 wird nicht angeboten. Das ist kein allgemeiner REST-Zugang über einen Mail-API-Key. Die SMTP-Submission für Geschäftsanwendungen ist ein eigener Versandweg und ersetzt keinen Lesezugriff. [Proton: IMAP, SMTP und POP3](https://proton.me/support/imap-smtp-and-pop3-setup), [offizieller Bridge-Quellcode](https://github.com/ProtonMail/proton-bridge).

Empfehlung: Bridge auf einem ausdrücklich ausgewählten Host betreiben und den Connector an dessen lokal geschützten IMAP-Zugang anbinden. Die Installation, dauerhafte Ausführung und Erreichbarkeit auf der Test-VM sind separate Infrastrukturarbeit. Keinen ungeschützten IMAP-Port im Netz öffnen. SMTP-Senden später als eigene freizugebende Aktion behandeln.

## Gmail

Die Gmail API verwendet OAuth 2.0. `gmail.readonly` liest Nachrichten und Einstellungen; `gmail.metadata` liefert Metadaten ohne Nachrichtentext. Beide gehören zu den eingeschränkten Scopes. Google beschreibt zusätzliche Verifikations- und gegebenenfalls Sicherheitsprüfungen bei entsprechenden Anwendungen und serverseitiger Speicherung/Übertragung. Ein API-Key ersetzt die Benutzerautorisierung nicht. [Google: Gmail API Scopes](https://developers.google.com/workspace/gmail/api/auth/scopes).

Empfehlung: Einrichtungsassistent mit OAuth-Client, sichtbarem Kontostatus und „Verbindung trennen“. Zunächst Lesen mit engen Label-/Zeitfiltern, Anhänge separat auswählbar. Versand, Löschen und Labeländerungen benötigen eigenständige Fähigkeiten und Berechtigungen. Voraussetzungen für den konkreten privaten OAuth-Betrieb vor Umsetzung prüfen.

## immocloud

immocloud erklärt ausdrücklich, dass keine öffentliche REST-/GraphQL-API, keine Webhooks und keine dauerhafte automatisierte KI-/n8n-Live-Anbindung angeboten werden. Verfügbar sind unter anderem Finanz-Excel, EÜR/Anlage V als PDF/Excel, DATEV-ZIP und separate Exporte persönlicher Daten und Dokumente. Dokumente lassen sich an eine persönliche Dokumentenadresse senden; Zuordnung zu Objekten/Buchungen bleibt manuell. [immocloud: Schnittstellen und APIs](https://help.immocloud.de/de/articles/15554579-welche-schnittstellen-und-apis-bietet-immocloud).

Empfehlung: Importprofil mit Objekt-/Zeitraumzuordnung, Vorschau, Dublettenprüfung und belegbarer Herkunft. Darauf kann ein Use Case für Immobilienkennzahlen, CSV/Excel und Diagramme aufbauen. Als **Import**, nicht als aktive Live-Verbindung darstellen. Kein automatisiertes Schreiben von Buchungen versprechen.

## Synology

Synology dokumentiert SMB sowie Rechte pro freigegebenem Ordner. File Station besitzt eine offizielle HTTP-/HTTPS-API. DSM-API-Anmeldung erfolgt über `SYNO.API.Auth`, Benutzer/Passwort und Session; OTP bzw. Geräteinformationen sind je nach Konfiguration relevant. Eine generische API-Key-Anmeldung ist daraus nicht abzuleiten. Verfügbare API-Versionen können mit `SYNO.API.Info` ermittelt werden. [DSM-Anmeldefluss](https://kb.synology.com/en-global/DG/DSM_Login_Web_API_Guide/2), [DSM Login API Guide](https://global.download.synology.com/download/Document/Software/DeveloperGuide/Os/DSM/All/enu/DSM_Login_Web_API_Guide_enu.pdf), [File Station API](https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/FileStation/All/enu/Synology_File_Station_API_Guide.pdf), [Synology: Ordnerrechte](https://kb.synology.com/tr-tr/DSM/tutorial/How_to_manage_ACL_settings_on_your_Synology_NAS).

Empfehlung: Für Wissensdokumente zuerst SMB mit einem auf ausgewählte Ordner beschränkten Lesekonto. Dateiliste/Download über File Station bei entsprechendem Bedarf. Dateischreiben, Löschen, DSM-Administration und SSH bleiben getrennte Fähigkeiten; ein NAS-Profil erhält nicht automatisch Administratorrechte.

## Amazon: drei unterschiedliche Fälle

Für **normale private Käuferkonten** wurde keine offizielle allgemeine API zum Abruf sämtlicher eigener Bestellungen/Rechnungen bestätigt. Amazons Datenschutzinformation beschreibt die Anforderung eigener Daten. Import solcher selbst bereitgestellten Unterlagen ist ein belastbarer Weg; Aktualität und enthaltene Felder müssen am tatsächlichen Export geprüft werden. [Amazon: Datenschutzinformation mit Datenanforderung](https://m.media-amazon.com/images/G/03/legal/Previous_versions_Legal_policies/Privacy_notice/Amazon.de_Datenschutzerklaerung_08_07_2024.pdf) (historische Fassung; direkte deutsche Hilfeseiten waren bei dieser Recherche nicht abrufbar).

Für **Amazon Business** existiert eine eigene Reporting API mit Bestell-/Positions-/Lieferdaten, auch für Deutschland. Die offizielle Anleitung verlangt Zugangsgenehmigung durch das Amazon-Business-Team; Rollen werden zugewiesen. [Business Reporting API](https://docs.business.amazon.com/docs/reporting-api-overview), [Business API Onboarding](https://docs.business.amazon.com/docs/onboarding-overview).

Für **Verkäufer/Vendor** ist SP-API vorgesehen, mit Entwicklerprofil, passenden Rollen und OAuth oder Selbstautorisierung. Diese Handelsdaten sind kein Ersatz für private Käuferdaten. [SP-API Onboarding](https://developer-docs.amazon.com/sp-api/docs/onboarding-overview).

Empfehlung: Kontotyp vor Einrichtung auswählen. Privat: Import. Business: offiziellen Zugang klären und dann Reporting. Händler: eigener SP-API-Connector. Keine Bestellungen, Zahlungen oder Vertragsänderungen aus der bloßen Verbindung ableiten.

## CHECK24

CHECK24 beschreibt im Kundenkonto zentral einsehbare Vergleiche, Angebote, Abschlüsse und Vertragsinformationen. Dokumente sind unter anderem im VersicherungsCenter vorgesehen. Eine allgemeine öffentliche Privatkonto-API wurde in den geprüften offiziellen Quellen nicht bestätigt. CHECK24 erwähnt direkte Händlerschnittstellen in seinem Preisvergleich; deren Existenz belegt keinen Zugang zu einem privaten Vertragskonto. [Kundenkonto/Vertragsdaten](https://www.check24.de/reiseversicherung/datenschutz/), [VersicherungsCenter](https://www.check24.de/versicherungscenter/), [Händlerschnittstellen](https://preisvergleich.check24.de/ul/lp/agb/).

Empfehlung: Selbst bereitgestellte Vertrags-/Angebotsdokumente oder ausgewählte Mails als Datenbasis, mit Anbieter, Stand und Herkunft. Live-Zugriff erst nach bestätigter passender Schnittstelle. C24-Bank-/PSD2-Verbindungen separat behandeln; sie gewähren keinen universellen CHECK24-Vertragszugriff.

## Konsequenz für die generische Integrationsverwaltung

Eine einheitliche Übersicht kann alle Profile zeigen, während jeder Typ seine echten Voraussetzungen behält: API-Token, OAuth, lokale Bridge, NAS-Session, SSH oder Dateiimport. „Aktiviert“, „Zugang eingerichtet“, „zuletzt geprüft“ und „für diesen Lauf ausgewählt“ sind unterschiedliche Zustände. Ein verbundenes Profil ist noch keine getestete Fähigkeit.

Projekt-/Aufgabenbindungen speichern Profil-IDs und gewählte Lesefähigkeiten. Chat-Auswahl kann diese für einen Lauf übernehmen oder abwählen. Deaktivieren sperrt neue Zugriffe auch für gespeicherte Bindungen. Importprofile zeigen den letzten Importstand statt einen irreführenden Online-Status. Private abgerufene Inhalte bleiben nach den geltenden Projekt-/Wissensregeln lokal, auch wenn der aktuelle Chat Auto oder Cloud verwendet.

Eine allgemeine Browser-Automation ist kein bestätigter API-Ersatz. Anmeldung, MFA, Seitenänderungen und mögliche Schreibschritte benötigen einen gesonderten ausführbaren Entwurf und reale Tests. Die hier geprüften Dienste sollten deshalb keine vorgetäuschten „Verbunden“-Karten durch bloßes Speichern einer URL erhalten.
