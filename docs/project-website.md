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

`.github/workflows/pages.yml` validates the website, runs its browser checks and
uploads only the sanitized build. Pushes to `milestone/m3-actions` and `main`
validate and prepare the site automatically. Publication is enabled only when
the repository variable `SHOWCASE_PAGES_ENABLED` is `true` and the account supports
Pages from this private repository. When changing the active delivery
branch, update the workflow branch filter. Never deploy from pull-request events.
GitHub Pages must be enabled with build type `workflow`; the account plan must
support Pages from private repositories. If the account disallows that, preserve
the private repository and report the deployment blocker.

Public URL after successful activation: `https://sschluet.github.io/obdaAI/`.
Verify the rendered live page, assets and deployment state before claiming it live.

07.10.2026: GitHub rejected Pages activation with HTTP 422 because the current
account plan does not support Pages for this private repository. Deployment remains
disabled; a separate public website-only repository was proposed and requires
the user's explicit approval. No public repository has been created yet.
