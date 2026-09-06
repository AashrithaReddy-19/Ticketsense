# Software Bill of Materials (SBOM)

`backend-sbom.json` and `frontend-sbom.json` in this directory are real
CycloneDX 1.5 SBOMs generated from this repository's actual dependency
environments — not hand-written or fabricated. They are point-in-time
snapshots committed as an example of the real output; the CI workflow
(`.github/workflows/ci.yml`, `sbom` job) regenerates a fresh SBOM from the
actual installed environment on every build and uploads it as a build
artifact, so the authoritative SBOM for any given commit is the one CI
produces for that commit, not the committed snapshot.

Honest scope note: `backend-sbom.json` was generated with
`cyclonedx_py environment`, which enumerates the *entire* active Python
environment — including dev/test tooling (pytest, cyclonedx-bom itself,
etc.), not only the packages actually shipped in the production Docker
image. It over-reports rather than silently omitting anything.

## Regenerating locally

Backend (from `backend/`, with the project's dependencies installed):

```
pip install cyclonedx-bom
python -m cyclonedx_py environment --output-format json --output-file ../docs/sbom/backend-sbom.json
```

Frontend (from `frontend/`):

```
npx --yes @cyclonedx/cyclonedx-npm --output-file ../docs/sbom/frontend-sbom.json
```

## Dependency vulnerability scanning

Run alongside SBOM generation, in the `dependency-audit` CI job:

- `pip-audit` (backend) — as of this writing, a clean scan of every runtime
  dependency in `backend/pyproject.toml` reports **no known vulnerabilities**.
- `npm audit --omit=dev` (frontend) — as of this writing, the only reported
  issue is a moderate-severity Vite/esbuild dev-server-only advisory
  (GHSA-67mh-4wv8-2f99: "esbuild enables any website to send any requests to
  the development server and read the response"). It does not affect the
  production build this repository ships (the vulnerable code path is the
  local `vite dev` server, never included in `vite build` output), and the
  available fix requires a breaking major-version upgrade of Vite and
  Vitest that was deliberately deferred rather than applied unverified this
  late in the effort — tracked here as an honest, open item rather than
  silently fixed or silently ignored. `react-router-dom` was bumped from
  7.9.1 to 7.18.3 in this same effort, which did close a real set of
  high/critical-severity advisories in `react-router` with no test or
  build regressions.

Both scans are wired into CI as non-blocking (`continue-on-error: true`)
so a newly published advisory in a transitive dependency doesn't silently
block every future change — a human reviews the report instead.
