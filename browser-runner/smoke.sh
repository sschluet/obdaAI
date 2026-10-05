#!/bin/bash
# Synthetic integration test only. No credentials, network or existing services.
set -euo pipefail
root=$(mktemp -d /tmp/obdaai-browser-test.XXXXXX)
name=obdaai-browser-test-${RANDOM}-${RANDOM}
cleanup() { docker stop "$name" >/dev/null 2>&1 || true; sudo rm -rf -- "$root"; }
trap cleanup EXIT
mkdir "$root/requests" "$root/results"
python3 - "$root" <<'PY'
import json,sys,hashlib
from pathlib import Path
html='<h1>OBDAAI_OFFLINE_BROWSER_TEST</h1><script>document.body.innerText="SCRIPT_EXECUTED"</script><img src="http://169.254.169.254/latest/meta-data/"><iframe src="file:///etc/passwd"></iframe>'
p=Path(sys.argv[1])/'requests/11111111-1111-4111-8111-111111111111.json'
p.write_text(json.dumps({'id':p.stem,'html':html,'sha256':hashlib.sha256(html.encode()).hexdigest()}))
PY
sudo chown -R 10001:10001 "$root"
sudo chmod -R 0700 "$root"
docker run --detach --rm --name "$name" --network none --user 10001:10001 --read-only --init --tmpfs /tmp:size=256m,mode=1777 --shm-size=128m --cap-drop ALL --security-opt no-new-privileges:true --security-opt "seccomp=$PWD/browser-runner/seccomp.json" --memory 768m --cpus 1 --pids-limit 128 -v "$root/requests:/browser-requests:ro" -v "$root/results:/browser-results" obdaai-browser-ci
for i in $(seq 1 45); do sudo test ! -f "$root/results/11111111-1111-4111-8111-111111111111.json" || break; sleep 1; done
sudo python3 - "$root" <<'PY'
import json,sys,base64
from pathlib import Path
r=json.loads((Path(sys.argv[1])/'results/11111111-1111-4111-8111-111111111111.json').read_text())
assert not r.get('error'),r.get('error')
assert r['text']=='OBDAAI_OFFLINE_BROWSER_TEST' and r['network'] is False and r['javascript'] is False
assert base64.b64decode(r['png'],validate=True).startswith(b'\x89PNG\r\n\x1a\n')
print('Real isolated Chromium snapshot passed; no network, active sandbox and JavaScript disabled.')
PY
