#!/usr/bin/env bash
set -euo pipefail
fixture_dir=$(mktemp -d /tmp/obdaai-artifact-ci.XXXXXXXX)
mkdir "$fixture_dir/requests" "$fixture_dir/results"
chmod 0777 "$fixture_dir" "$fixture_dir/requests" "$fixture_dir/results"
image=${1:-obdaai-artifacts-ci}
limits=(--rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 80 --memory 1g --cpus 1 --tmpfs /tmp:size=128m,mode=1777)
cleanup() {
  # Child directories are private and owned by the nonroot container user.
  # Remove only this freshly generated fixture through that same identity.
  docker run "${limits[@]}" -v "$fixture_dir/requests:/requests:rw" \
    -v "$fixture_dir/results:/results:rw" --entrypoint python "$image" -c \
    'import pathlib,shutil; [shutil.rmtree(p) for root in ("/requests","/results") for p in pathlib.Path(root).iterdir()]' || true
  rm -rf -- "${fixture_dir:?}"
}
trap cleanup EXIT
docker run "${limits[@]}" -v "$fixture_dir/requests:/requests:rw" \
  --entrypoint python "$image" /app/artifact_smoke.py prepare
docker run "${limits[@]}" -v "$fixture_dir/requests:/requests:ro" \
  -v "$fixture_dir/results:/results:rw" --entrypoint python "$image" \
  /app/artifact_smoke.py render
docker run "${limits[@]}" -v "$fixture_dir/requests:/requests:ro" \
  -v "$fixture_dir/results:/results:ro" --entrypoint python "$image" \
  /app/artifact_smoke.py check
