# Public project website

The user authorized a public GitHub Pages project presentation on 07.10.2026.
The application and repository remain private. Website source lives in `website/`;
only the explicit allowlist in `scripts/build_showcase.py` becomes public.

## Contents and upkeep

`website/project.json` holds the full feature catalog, implementation/acceptance
status, screenshot captions, last tested application release and CI evidence.
Update its date, relevant features and roadmap with each project delivery.
Update affected screenshots when the UI changes. Website build revision is
generated automatically and is separate from the last tested application release.
Do not relabel historical mixed-load tests as tests of a later release.

Screenshots show the real application UI with isolated synthetic examples. They
are UI illustrations and do not prove real provider or external-system acceptance.
No private GitHub docs, secrets, runtime state or production screenshots are public.

## Synthetic screenshot capture

Use a fresh dedicated fixture directory, never production or an existing QA fixture:

```sh
HUB_BROWSER_FIXTURE_DIR=.local/website-fixture \
HUB_BROWSER_ORIGIN=http://127.0.0.1:18767 \
uv run uvicorn scripts.browser_fixture:app --host 127.0.0.1 --port 18767
```

For initial setup, seed the sample conversation with
`uv run python scripts/seed_showcase.py`; repeat seeding is safe. The capture script
adds synthetic project documents and paused example tasks through the real UI:

```sh
cd frontend
node capture-showcase.mjs
```

The capture script is restricted to the dedicated loopback origin. Stop only the
fixture process started for this task after capture. Inspect every public image.

## Validate and preview

```sh
uv run python scripts/build_showcase.py
python3 -m http.server 18768 --bind 127.0.0.1 --directory .local/website-build
cd frontend
node showcase-check.mjs
```

Browser checks cover the 43-feature initial catalog, search/filtering, gallery,
keyboard interaction and mobile overflow. Update expected feature counts alongside
intentional catalog changes. QA captures stay under `.local/showcase-qa`.

## Publication

GitHub rejected Pages activation in the private application repository (HTTP 422,
account plan). The user explicitly authorized a separate public repository on
07.10.2026: `sschluet/obdaAI-website`. App source and runtime data stay private.

`.github/workflows/pages.yml` validates the public-file allowlist and runs website
browser checks on each push to `milestone/m3-actions` or `main`. Once its exact
commit passes, publishing the site is a required delivery step:

```sh
uv run python scripts/publish_showcase.py
```

The publisher requires a clean committed working tree, successful website CI for
that exact commit and the authorized public target. It copies only the validated
build into a temporary checkout, creates a normal commit and pushes without force.
It uses the operator's existing GitHub CLI authentication; no new token is copied
into Actions secrets. GitHub Pages automatically publishes the public repo's main
branch root. Source revision is generated separately from the tested app release.

When changing the active delivery branch, update the private CI branch filter.
Feature/status changes and affected screenshots must be maintained before each
publication. Verify Pages build success and the live page/assets after publishing.

Public URL: `https://sschluet.github.io/obdaAI-website/`.

Initial public deployment passed on 07.10.2026: Pages build and live browser checks
for the complete feature catalog, asset loading, search/filtering, gallery/dialog/
keyboard navigation and 320–1440 px layouts. App source remained private.
