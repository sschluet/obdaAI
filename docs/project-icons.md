# Konfigurierbare Projektsymbole

Projekte erhalten ein wählbares Symbol aus einer kuratierten Lucide-Galerie. Die
Auswahl ist beim Erstellen und unter **Projekt bearbeiten** möglich. Ein vorhandenes
Projekt verwendet zunächst das Ordnersymbol; ältere API-Clients erhalten diese
Voreinstellung und ändern bestehende Symbole bei Updates ohne `icon` nicht.

Gespeichert wird ausschließlich ein validierter Symbolname. Es gibt keine externen
Bildabrufe, Tracking-URLs oder benutzerdefinierten SVG-Code. Das Symbol ist visuelle
Projektmetadaten und verändert weder Quellenrechte noch KI-Routing oder Prompts.
Die Darstellung erfolgt lokal durch statisch eingebundene Lucide-Komponenten.

Lucide erlaubt private und kommerzielle Verwendung unter ISC; einige von Feather
abgeleitete Symbole verwenden MIT. Die vollständigen Hinweise der verwendeten
Version sind unter `frontend/public/assets/licenses/lucide.txt` und auf der
öffentlichen Website unter `assets/lucide-license.txt` enthalten. Quelle:
https://lucide.dev/license. Es handelt sich um allgemeine Symbole, keine exklusiven
Markenlogos.

Migration0033 ergänzt das Symbolfeld mit Ordner-Voreinstellung für vorhandene
Projekte. Abnahmebelege und getesteter Release stehen in STATUS.md.
