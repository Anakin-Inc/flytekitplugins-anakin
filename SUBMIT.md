# flytekitplugins-anakin: status and release steps

Not shipped in the sdist (excluded in `pyproject.toml`).

## Route

Flyte doesn't take third-party integrations into its repo:
`flyteorg/flytekit/plugins/README.md` says plugins "can be authored in an
independent repository" and "it is not necessary to add plugins here". So the
route is a PyPI package named `flytekitplugins-anakin` (the
`flytekitplugins.<name>` namespace convention every flytekit plugin uses), plus
an install guide at anakin.io/docs/integrations/workflow/flyte.

Plain `@task` functions, not a `PythonTask` subclass or connector: Anakin is an
HTTP API, so nothing needs a backend component on the cluster.

## Verified (2026-10-28)

- Ported to `anakin-sdk` 0.2.0. 23 of 24 tasks call the SDK; only
  `browser_task` calls `POST /ai/evaluate` directly. Wire actions now take
  `credential_id` / `identity_id` (0.1 couldn't).
- Return types fixed for flytekit: `dict[str, Any]` made flytekit pickle each
  value and fail on any `null` ("Cannot pickle None Value"), which broke the
  old `ai_visibility_search` test. JSON inputs/outputs are now plain `dict`;
  SDK results are returned as their Pydantic models.
- `pytest`: 53 passed (unit tests call tasks through flytekit local execution,
  so the type engine runs on every input and output), on flytekit 1.16.31 /
  Python 3.12, flytekit 1.14.9 / Python 3.10 and flytekit 1.16.31 / Python 3.13.
- `ruff check`, `ruff format --check`, `mypy flytekitplugins`: clean.
- `uv build` + `twine check --strict`: pass. The wheel has no
  `flytekitplugins/__init__.py`, so it coexists with other flytekit plugins;
  a clean-venv install imports all 24 tasks.
- Live, against api.anakin.io, with `pyflyte run`:
  - `scrape_pages_wf` (map_task over `scrape_url`), keyless
  - `wire_lookup_wf` (`wire_discover` + `wire_catalog`), keyless
  - `research_wf` (`search` -> `scrape_url` -> `agentic_search`), with a key
  - `tests/test_live.py`: keyless scrape/Wire plus keyed reads of AI
    visibility sources, Wire identities, sessions and monitors: 3 passed
  - Every snippet in README.md and the anakin.io docs page.
- Not run live: write tasks (`wire_write_action`, `wire_login`, `wire_build`,
  `monitor_create`, `monitor_control`, `session_delete`) and `browser_task`,
  to avoid changing account state. They're covered by unit tests.
- Not run on a real Flyte cluster (no cluster here). The secret request is the
  documented `Secret(group="anakin", key="api-key")`; locally a missing secret
  raises `ValueError`, which the tasks catch before falling back to
  `ANAKIN_API_KEY`.

## Release steps

1. Merge this branch to `main` of `Anakin-Inc/flytekitplugins-anakin`.
2. On PyPI (account that should own the project): Publishing -> Add a new
   pending publisher: project `flytekitplugins-anakin`, owner `Anakin-Inc`,
   repository `flytekitplugins-anakin`, workflow `publish.yml`, environment
   `pypi`. Create the `pypi` environment in the GitHub repo settings.
3. Tag and push: `git tag v0.1.0 && git push origin v0.1.0`. The workflow
   tests, builds, checks the tag matches `_version.py`, and publishes.
4. Check `pip index versions flytekitplugins-anakin` shows 0.1.0.
5. Merge the docs page in Anakin-Inc/blueprint-scribe-35#1855 and run its
   deploy workflow (it's `workflow_dispatch` only).
6. Optional: PR a row into `flyteorg/flytekit` `plugins/README.md` for
   discoverability.
