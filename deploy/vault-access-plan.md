# Reviewbarer Zugang zum vorhandenen Vault

Dieser Plan ist vorbereitet, nicht ausgeführt. Der bestehende Vault und dessen
Synchronisation bleiben kanonisch. Kein neuer Syncthing-/Obsidian-Sync-Dienst.
Die AGENTS-Regel für Änderungen an bestehenden Ressourcen verlangt die gesonderte
Freigabe: allgemeine Markdown-Quellen lesen, ausschließlich `AI/Memory/` schreiben.

## Vorgesehene Verbindung

- Eigenes Dienstkonto auf dem bestehenden Vault-Server, kein Administrator, kein
  Passwort, eigene SSH-Key-Identität nur von der obdaAI-VM.
- OpenSSH `internal-sftp`, eigenes root-eigenes Chroot, keine Shell, keine Agent-,
  X11-, TCP- oder Remote-Forwardings, kein TTY. Chroot enthält ausschließlich den
  Vault als readonly Bindmount und darüber ausschließlich den freigegebenen
  Memory-Unterordner als writable Bindmount. Vorher Mounts/Ownership prüfen;
  vorhandene Vault-Eigentümer oder Sync-Identitäten nicht ersetzen.
- Vault-Konfiguration/Plugins nicht indexieren; `.obsidian` im Zugang maskieren.
- Nur den notwendigen Gruppen-/Dateizugang prüfen, keine pauschalen sudo-Rechte.
  Memorydateien müssen mit dem vorhandenen Sync-Benutzer lesbar sein.
- Auf eigener VM ein SFTP-Dateisystemzugang unter `/mnt/obdaai-vault`, eigener
  privater Schlüssel und exakt gepinnter Serverhostkey. Kein Agent-Forwarding.
  Mount hat bounded Reconnect/Timeout; Ausfall meldet Fehler, kein leeres Index-
  Reconcile, kein Wiederbeleben gelöschter Inhalte, kein lokales konkurrierendes Vault.
- Nur App-/Memory-Worker erhalten dieses Volume; Offline-Parser ausdrücklich nicht.
  Schreiben außerhalb `AI/Memory` muss zusätzlich serverseitig scheitern.

## Abnahme und Rückweg

Synthetische Memory-Dateien innerhalb des freigegebenen Bereichs: App→Vault,
Vault→App, Rename, Delete, Konflikt, Revisionvergleich, Restart und Offlinefall.
Originale/private Notizen nicht als Testmaterial verwenden. Vorhandenen Sync mit
readonly Health prüfen; synthetischen Marker am bestehenden Ziel nachweisen.
Rückweg: nur neuen Mount/Units/SSH-Key/Zugangsaccount deaktivieren, neuen readonly
Bindmount lösen. Vorhandene Synchronisation und Vault-Inhalte erhalten.

Ein eigener begrenzter Zugriff auf den vorhandenen JSON-Websuchdienst wird separat
benötigt: vorzugsweise ein zweites SSH-Keykonto ohne Shell mit ausschließlich
`PermitOpen 127.0.0.1:<verifizierter Suchport>` vom obdaAI-Ursprung. Keine alten Admin-
oder Assistant-Credentials auf die eigene VM kopieren. Keine allgemeine Netzfreigabe.
