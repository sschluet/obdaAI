# Public project website

The user authorized a public GitHub Pages project presentation on 07.10.2026.
The application runtime and user data remain private. On 11.10.2026 the user
explicitly confirmed public visibility of `sschluet/obdaAI`; source visibility
does not authorize publishing private documents or runtime data. Website source lives in `website/`;
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

Browser checks cover the current feature catalog, search/filtering, gallery,
keyboard interaction and mobile overflow. Catalog counts are checked from the versioned project metadata. QA captures stay under `.local/showcase-qa`.

## Publication

The user initially authorized a separate public website repository on 07.10.2026
because GitHub Pages was unavailable for the then-private app repository.
On 11.10.2026 they explicitly requested public obdaAI, migration of Pages into
that repository and deletion of obdaAI-website after the new site is verified.
The old website main history is preserved as obdaAI's `gh-pages` branch and in a
local mirror before deletion. Application source branches remain unchanged.

`.github/workflows/pages.yml` validates the public-file allowlist and runs website
browser checks for relevant public files/build scripts on pushes to milestone
branches or main; manual dispatch is also available. Pure documentation changes
do not trigger the website workflow or require publication. Once a delivery
affecting the public site passes its exact website CI, publish it:

```sh
uv run python scripts/publish_showcase.py
```

The publisher requires a clean committed working tree, successful website CI for
that exact commit and the authorized public `sschluet/obdaAI` target. It explicitly
clones only `gh-pages`, validates all existing files against the website allowlist,
creates a normal commit and pushes only to `refs/heads/gh-pages` without force.
It uses existing GitHub CLI authentication; no new Actions token is needed.
GitHub Pages is configured for **Deploy from a branch → gh-pages → /(root)**.
The branch contains only generated website files and synthetic screenshots;
application sources, documents and runtime data are never copied into that branch.

Source revision is generated separately from the tested app release. Publishing
gh-pages does not redeploy the test VM or merge application code into main.
Website CI accepts main and milestone/** branches. Both workflows cancel
superseded runs per ref. See [CI scope and proof](ci-efficiency.md).
After every publication, verify Pages build success, exact public build.json
revision, catalog, screenshots and content hashes before reporting completion.

Public URL: `https://sschluet.github.io/obdaAI/`.
The old obdaAI-website URL will cease to work after repository deletion. No custom
DNS or application-domain configuration is changed by this Pages migration.
