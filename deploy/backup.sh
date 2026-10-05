#!/bin/bash
# Streaming, public-key-only backup of this dedicated VM. No plaintext dump on disk.
set -euo pipefail
[[ $(hostname -s) = obdaai && $(id -u) = 0 ]] || exit 1
umask 077
exec 9>/run/lock/obdaai-backup.lock
flock -n 9 || exit 0
root=/var/backups/obdaai
recipients=/etc/obdaai/backup-recipients
[[ -s "$recipients" && ! -L "$recipients" ]]
size=$(docker exec obdaai-db-1 psql -U hub -d hub -Atc 'select pg_database_size(current_database())')
[[ "$size" =~ ^[0-9]+$ ]]
used=$(du -sb "$root" | cut -f1)
free=$(df -B1 --output=avail "$root" | tail -1 | tr -d ' ')
source_size=$(du -sb /var/lib/obdaai 2>/dev/null | cut -f1 || echo 0)
vault_archive=()
vault_size=0
if [[ -f /etc/obdaai/runtime.env ]] && grep -q '^HUB_VAULT_DIR=/vault$' /etc/obdaai/runtime.env; then
  mountpoint -q /mnt/obdaai-vault || { echo 'Configured Vault mount unavailable; no incomplete backup'; exit 1; }
  vault_size=$(du -sb /mnt/obdaai-vault/AI/Memory | cut -f1)
  vault_archive=(-C /mnt/obdaai-vault AI/Memory)
fi
access_archive=()
for p in var/lib/obdaai-access/.ssh etc/systemd/system/obdaai-vault-mount.service etc/systemd/system/obdaai-search-relay.service opt/obdaai/vault.compose.yaml opt/obdaai/scheduler.compose.yaml; do
  [[ ! -e /$p ]] || access_archive+=("$p")
done
estimate=$((size * 3 + source_size * 2 + vault_size * 2 + 52428800))
((used + estimate < 10737418240 && free - estimate > 1073741824)) || { echo 'Backup storage reserve reached'; exit 1; }
id=$(date -u +%Y%m%dT%H%M%S.%NZ)
staging="$root/.incomplete-$id"
mkdir -m 700 "$staging"
cleanup() { [[ ! -d "$staging" ]] || rm -rf -- "$staging"; }
trap cleanup EXIT
docker exec obdaai-db-1 pg_dump -U hub -d hub -Fc | age --encrypt -R "$recipients" -o "$staging/database.pgdump.age"
tar -C / -czf - \
  etc/obdaai etc/ssh home/hub-deploy/.ssh var/lib/obdaai-relay/.ssh var/lib/obdaai \
  opt/obdaai/compose.yaml opt/obdaai/https.compose.yaml \
  usr/local/sbin/obdaai-egress usr/local/sbin/obdaai-https-network \
  etc/systemd/system/obdaai-egress.service \
  etc/systemd/system/obdaai-model-relay.service \
  etc/systemd/system/obdaai-https-network.service \
  etc/systemd/system/docker.service.d/obdaai-egress.conf \
  etc/systemd/system/nginx.service.d/obdaai-network.conf \
  etc/nginx/sites-enabled/obdaai "${access_archive[@]}" "${vault_archive[@]}" | age --encrypt -R "$recipients" -o "$staging/config.tar.gz.age"
(cd "$staging" && sha256sum database.pgdump.age config.tar.gz.age > SHA256SUMS)
printf 'format=obdaai-age-v1\nutc=%s\n' "$id" > "$staging/manifest.txt"
mv -- "$staging" "$root/snapshot-$id"
echo "Encrypted snapshot completed: snapshot-$id"
