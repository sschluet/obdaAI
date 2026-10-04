#!/bin/bash
# Run only on the new, dedicated obdaAI guest, never an existing host.
set -euo pipefail
[[ $(id -u) = 0 && $(hostname -s) = obdaai ]] || { echo 'Unexpected host/user'; exit 1; }
. /etc/os-release
[[ "$ID" = debian && "$VERSION_ID" = 13 ]] || { echo 'Expected Debian 13'; exit 1; }
[[ ! -e /etc/obdaai ]] || { echo 'Already bootstrapped; inspect before retry'; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg qemu-guest-agent python3
install -d -m 0755 /etc/apt/keyrings
curl --fail --silent --show-error https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
fingerprint=$(gpg --show-keys --with-colons /etc/apt/keyrings/docker.asc | awk -F: '$1=="fpr" {print $10; exit}')
[[ "$fingerprint" = 9DC858229FC7DD38854AE2D88D81803C0EBFCD88 ]] || { echo 'Docker key mismatch'; exit 1; }
chmod 0644 /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<'SOURCE'
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: trixie
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
SOURCE
apt-get update -qq
packages=(docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin)
pinned=()
for package in "${packages[@]}"; do
  candidate=$(apt-cache policy "$package" | awk '/Candidate:/ {print $2}')
  [[ -n "$candidate" && "$candidate" != '(none)' ]] || exit 1
  pinned+=("$package=$candidate")
done
# Set non-overlapping pools before the package starts Docker for the first time.
install -d -m 0755 /etc/docker
[[ ! -e /etc/docker/daemon.json ]] || { echo 'Unexpected Docker config'; exit 1; }
cat > /etc/docker/daemon.json <<'DOCKER'
{"bip":"172.30.240.1/24","default-address-pools":[{"base":"172.30.0.0/16","size":24}]}
DOCKER
apt-get install -y -qq "${pinned[@]}"
install -d -m 0700 /etc/obdaai /etc/obdaai/secrets /var/backups/obdaai
# Create once on the dedicated server; never in the image or database.
python3 - <<'KEY'
import base64, os
fd = os.open('/etc/obdaai/secrets/provider-encryption.key', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
os.fchown(fd, 10001, 10001)
with os.fdopen(fd, 'w') as stream:
    stream.write(base64.b64encode(os.urandom(32)).decode() + '\n')
KEY
install -d -m 0755 /opt/obdaai/releases
systemctl enable --now docker qemu-guest-agent
dpkg-query -W -f='${Package} ${Version}\n' "${packages[@]}" > /etc/obdaai/packages.lock
echo 'Dedicated guest Docker bootstrap completed.'
