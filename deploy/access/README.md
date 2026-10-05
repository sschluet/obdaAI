# M2 access configuration review

Prepared templates, not an installer and not applied to production. Authorization
must cover the two service accounts, two new SSH identities, SSHFS, bounded exports
and relays, dedicated VM runtime/egress changes and validated SSH reload. A blocked
approval must never be bypassed by a different execution mechanism.

## Inventory and preservation

Reconfirm canonical Vault path, no symlink or nested mounts, owner/read group and
Sync process identity. Verify actual local JSON search endpoint. Snapshot metadata,
existing SSH configuration and own VM compose/runtime/network units for rollback.
No old assistant private keys are transferred. Generate keys on the dedicated VM.

## Server controls

New locked non-admin accounts only; root-owned public authorized_keys outside writable
homes, mode 0644 so the unprivileged SSH authentication process can read them;
private keys remain 0600. SFTP account belongs to the existing Vault read group. The dedicated new
Memory directory uses the Sync user's existing primary group with setgid so app
files are readable by the running Sync; test incoming edit/atomic replacement and
actual Sync status rather than assuming group membership proves bidirectionality.
Do not change existing note ownership, existing Sync credentials or its service.

Root-owned chroot exposes the canonical Vault with a readonly bind mount. A nested
bind exposes only AI/Memory writable. Mask .obsidian using an empty readonly mount.
Check mount flags after each operation. Keys restrict source to the dedicated VM's
verified address. Vault key uses restrict; search key uses restrict,port-forwarding
with permitopen="127.0.0.1:8888". The Match block independently denies all other
forwarding, sessions, agent, PTY and passwords. Search account has no shell session
(MaxSessions 0); its local TCP forwarding reaches only the verified search port.

Render sshd-vault-search.conf.in to a new dedicated drop-in, ensure no old users
match, validate sshd -t and both effective sshd -T -C profiles before reload. Keep
existing sessions and public/private server host identity unchanged.

## Dedicated VM controls

Pinned existing public hostkey only; no global TLS/SSH verification bypass. Vault
private key root-readable, search key readable only by its unprivileged relay user.
SSHFS uses reconnect, bounded ConnectTimeout/ServerAlive, allow_other with
kernel default_permissions and fixed app UID/GID mapping. Protect the underlying
unmounted mountpoint with mode 000 so a lost mount cannot look like an empty Vault.
Validate real FUSE I/O error handling and preserve index on outage.

Only API/chat worker and source/memory worker get /vault via the reviewed compose
override; parser has no Vault or secrets. Configure HUB_VAULT_DIR=/vault and bounded
Memory writes. Search relay binds loopback only; app UID egress permits only that
specific loopback port in addition to its existing rules. No general private-network
allow rule. Restore compose/runtime/egress and disable only the new units on rollback.
Encrypted own VM backup must include the two keys, known_hosts, new relay/mount units
and updated runtime. No private key or Vault content enters Git or model prompts.

## Live acceptance before M2 completion

Use uniquely marked synthetic content in AI/Memory only. Prove app→canonical Vault,
Vault→app, stable ID across rename, deletion/tombstone, revision conflict resolution,
restart/reconcile and an actual mount outage without index deletion. Verify outside
Memory and .obsidian writes/reads are denied at server boundary, not merely in UI.
Keep only recoverable test deletions and preserve user notes. Verify Sync remains
healthy and its actual peer behavior where accessible. Test the public synthetic
search through the new own VM relay, exact-query approval, URL/time provenance,
LOCAL_ONLY/private-history non-transmission and wrong-destination refusal. Existing
services unavailable is an explicit error, not a successful synthetic replacement.
