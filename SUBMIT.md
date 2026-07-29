# flytekitplugins-anakin — verification status

## Full coverage (`feat/full-tool-coverage`)

The initial build covered 3 of Anakin's 21 API capabilities
(`scrape_url`, `search`, `agentic_search`), by deliberate scope decision
(see below — still the correct call). This pass adds the remaining 18 as
`@task` functions, same pattern, following two strategies chosen per
capability based on what `anakin-sdk` v0.1.0 actually implements (read
directly from `anakin-py/src/anakin/client.py` in full, not assumed):

- **6 wrap `anakin-sdk`** (like the original 3): `map_site` (`Anakin.map`),
  `crawl_site` (`Anakin.crawl`), `wire_read_action` / `wire_write_action`
  (both call `Anakin.wire`, split into two tasks purely so a workflow
  author's choice of task is an explicit signal about whether a step can
  change state on a third-party site — mirrors the same split in
  `anakin-mcp/src/tools/wire.ts`), `session_list` / `session_delete`
  (`Anakin.sessions.list` / `.delete`).
- **12 call the REST API directly** via a small `httpx`-based helper
  (`flytekitplugins/anakin/_http.py`), because `anakin-sdk` v0.1.0 doesn't
  implement them: `wire_discover`, `wire_catalog`, `wire_identities`,
  `wire_login`, `wire_build`, `monitor_create`, `monitor_list`,
  `monitor_changes`, `monitor_control`, `ai_visibility_sources`,
  `ai_visibility_search`, `browser_task`. Every path/verb/poll-target for
  these was read from `anakin-mcp/src/client.ts` — Anakin's own MCP server,
  a second independent implementation against the same REST API — not
  invented. `_http.py` reuses the same auth header, dual-shape error
  tolerance, and retry/poll backoff `anakin._http.HttpClient` applies
  internally to SDK-covered endpoints, so error/retry behavior is
  consistent across every task in this package.

One correction to the original scope-decision text below: this pass found
`anakin-sdk`'s `Anakin.sessions` sub-client (`list`/`create`/`save`/
`update`/`delete`) already covers browser-session listing and deletion —
contrary to an initial assumption that all of `monitor_*`/`ai_visibility_*`/
`session_*`/`browser_task` were missing from the SDK. Verified directly
against `anakin-py/src/anakin/client.py`'s `SessionsClient` class before
writing `session_list`/`session_delete`, so those two route through the SDK
like the original 3 tasks, not through `_http.py`.

`anakin-sdk` v0.1.0's `Anakin.wire()` does not accept `credential_id` /
`identity_id`, though the REST API supports both for auth-required actions
(`WireRunOptions` in `anakin-mcp/src/client.ts`) — `wire_read_action` /
`wire_write_action` inherit that gap and will raise `WireAuthRequiredError`
for actions needing auth until the SDK adds the parameter. Documented in
both `README.md` and the tasks' own docstrings, not silently dropped.

`pyproject.toml`'s `Repository`/`Issues` URLs were also corrected in this
pass — they pointed at `Anakin-Inc/anakin-flyte-plugin`, but `git remote -v`
shows the real repo is `Anakin-Inc/flytekitplugins-anakin` (matching the
published package name, and this repo's actual `origin`).

Tests: `tests/test_tasks.py` grew from 5 to 29 tests, covering all 21
tasks — SDK-backed tasks mock `flytekitplugins.anakin.tasks.Anakin`
(unchanged pattern); the 12 raw-HTTP tasks mock
`flytekitplugins.anakin.tasks._http.request`/`.poll` to test the
task-to-REST wiring (method, path, body, response shaping — including the
`alertWebhookSecret` redaction on every monitor response and the
`full_content` stripping on `ai_visibility_search`) without hitting the
network. Same "never run, `flytekit` not installed here" caveat as below
applies to this expanded suite too.

## Live-verified, not assumed

- `anakin-sdk` is **live on PyPI right now** (confirmed via
  `curl https://pypi.org/pypi/anakin-sdk/json` → 200, version `0.1.0`).
  `pyproject.toml` depends on it normally (`anakin-sdk>=0.1.0,<0.2.0`) — no
  local path override needed or present, same as `airflow-provider-anakin`
  and `langchain-anakin`. `flytekit` current PyPI version confirmed via
  `curl https://pypi.org/pypi/flytekit/json` → `1.16.26`.

- **The scope decision — plain `@task` functions instead of a custom
  `PythonTask`/connector subclass — was made from real, current Flyte
  sources fetched live in this pass, not assumed:**
  - `https://github.com/flyteorg/flytekit/tree/master/plugins` and
    `plugins/README.md` (fetched via `raw.githubusercontent.com`) were used
    to survey real, current flytekit plugins and pick a comparably-scoped
    reference, per the task brief's instruction not to model against
    something huge like the Spark plugin. `flytekit-openai` was the
    closest fit — a "Flytekit-only" type plugin wrapping a third-party API
    (OpenAI), the same shape as this integration.
  - Fetching `flytekit-openai`'s actual source
    (`plugins/flytekit-openai/setup.py`,
    `flytekitplugins/openai/chatgpt/task.py`) showed its `ChatGPTTask`
    subclasses `PythonTask` and mixes in `SyncConnectorExecutorMixin` from
    `flytekit.extend.backend.base_connector` — meaning it requires a
    **connector service deployed on the Flyte backend cluster itself** to
    execute. That's real infrastructure, appropriate for OpenAI's
    async-job-with-polling-via-a-managed-service model, but not something
    to replicate for a plain synchronous/poll-in-process HTTP API.
  - `plugins/README.md` (flyteorg/flytekit's own plugin-authoring
    guidelines, fetched live) states plugins are "structured as micro-libs
    and can be authored in an independent repository" and "it is not
    necessary to add plugins here" — confirming an independent,
    non-monorepo package (this one) is the normal, sanctioned path, mirroring
    how `airflow-provider-anakin` is independent of `apache/airflow`.
  - The union.ai-hosted current docs page for "Task plugins"
    (`user-guide/task-configuration/task-plugins/`, fetched live) states
    directly: a standard `@task`-decorated Python function wrapping a
    third-party API call "requires no plugin machinery... it's simply a
    normal Python function," and that full plugin infrastructure is for
    "custom task execution templates beyond standard Python functions" —
    which does not describe Anakin's plain HTTP request/response and
    submit-and-poll endpoints.
  - This is the deliberate, evidence-backed answer to the task brief's own
    open question ("don't assume a full plugin is necessary if a much
    simpler path is what Flyte's own docs actually recommend") — the
    simpler path **is** what the docs recommend, and is what was built.

- **The namespace-package layout is still real and followed exactly**,
  per `plugins/README.md`'s guidelines section (fetched live):
  - Folder pattern `flytekit-<name>` for the repo, published package name
    `flytekitplugins-<name>`.
  - Namespace package structure: `flytekitplugins/anakin/__init__.py`, with
    **no `__init__.py` at the outer `flytekitplugins/` level** — verified
    with `ls -la` on the actual directory after creating it, not just
    assumed from the doc text.
  - `entry_points = {"flytekit.plugins": ...}` was read in both
    `flytekit-openai/setup.py` (present) and the guidelines template
    (present but commented out, described as "OPTIONAL... for Plugins where
    auto-loading on installation is desirable," specifically type/data
    plugins that must register a side effect — e.g.
    `TypeEngine.register(PanderaTransformer())` — at import time). This
    package's tasks have no such import-time side effect; they're used by
    explicit import like any function. Entry point deliberately omitted,
    documented here rather than silently applied or silently skipped.
  - `[tool.hatch.build.targets.wheel] packages = ["flytekitplugins"]` is
    hatchling's equivalent of the legacy setuptools
    `namespace_packages=["flytekitplugins"]` declaration seen in
    `flytekit-openai/setup.py` — hatchling includes the directory tree
    without requiring an `__init__.py` at the namespace root (PEP 420
    implicit namespace packages).

- **Pydantic BaseModel task I/O is real, current flytekit behavior, not
  guessed:** researched and confirmed flytekit >= 1.14 natively serializes
  Pydantic v2 `BaseModel` task inputs/outputs via MessagePack (replacing an
  earlier Protobuf-struct-based format that had int/float coercion issues).
  `pyproject.toml` pins `flytekit>=1.14.0,<2.0.0` specifically so
  `scrape_url`/`search`/`agentic_search` can return `anakin-sdk`'s
  `Document`/`SearchResult`/`AgenticSearchResult` Pydantic models directly
  as task outputs, unlike the Airflow provider (which had to flatten to
  `model_dump(mode="json")` dicts for XCom).

- **Secret handling follows Flyte's own documented pattern, not invented:**
  fetched `flyteorg/flyte`'s `docs/user_guide/productionizing/secrets.md`
  live and confirmed the `Secret(group=, key=)` + `secret_requests=[...]`
  on `@task` + `current_context().secrets.get(group, key)` retrieval
  pattern. Used `group="anakin", key="api-key"` here. Falls back to
  `ANAKIN_API_KEY` (the SDK's own env var fallback) when no secret is
  mounted, wrapped in a broad `except` in `_client()` so local execution
  (`pyflyte run`, or these unit tests) doesn't need a Flyte secret manager
  present at all.

- Every field/method referenced against real source, not assumed:
  `Anakin.__init__(api_key=, *, base_url=, ...)`, `client.scrape()`,
  `client.search()`, `client.agentic_search()` signatures and defaults
  (`country="us"`, `use_browser=False`, `generate_json=False`,
  `force_fresh=False` for scrape; `limit=5` for search; `use_browser=True`
  for agentic_search — note this default is `True`, opposite of scrape's,
  and `agentic_search`'s task signature preserves that distinction rather
  than flattening both to one default — see
  `test_agentic_search_default_use_browser_is_true` in
  `tests/test_tasks.py`) all read directly from
  `anakin-py/src/anakin/client.py`. Response shapes (`Document`,
  `SearchResult`, `AgenticSearchResult`) read from
  `anakin-py/src/anakin/models.py`.

- All 7 source files (`flytekitplugins/anakin/*.py` — `__init__.py`,
  `tasks.py`, `_http.py` — plus `example_workflows/*.py`, `tests/*.py`)
  pass `python3 -m py_compile` — syntactically valid. Output shown in this
  session's transcript.

## What's NOT verified

**`flytekit` was never actually installed or imported in this
environment** — `python3 -c "import flytekit"` fails with
`ModuleNotFoundError` (checked, not assumed), same
network-restricted-sandbox pattern hit by every other Python package built
this session (`langchain-anakin`, `airflow-provider-anakin`,
`dagster-anakin`). So:

- `tests/test_tasks.py` (29 tests as of `feat/full-tool-coverage`, up from
  5) was **written but never run**. SDK-backed tasks mock
  `flytekitplugins.anakin.tasks.Anakin` entirely; the 12 raw-HTTP tasks mock
  `flytekitplugins.anakin.tasks._http.request`/`.poll` — both are flytekit's
  own documented pattern for exercising tasks without a running Flyte
  backend ("local execution"), calling the `@task` functions directly — but
  that local-execution path itself still needs `flytekit` installed to
  build the `FlyteContext`, run the type engine's input/output transforms,
  etc. None of that was exercised here.
- `example_workflows/example_anakin.py` was `py_compile`d only — never run
  with `pyflyte run`, never registered or executed against a real Flyte
  cluster or `pyflyte serialize`d.
- The namespace-package wheel layout
  (`[tool.hatch.build.targets.wheel] packages = ["flytekitplugins"]`) was
  never actually built into a wheel (`python3 -m build` / `hatchling
  build`) — hatchling itself isn't installed here either. The directory
  structure was verified by hand (`ls -la`) against the guideline's
  described shape, not by building and inspecting a real wheel's contents.
- Whether `current_context().secrets.get(...)` actually raises (vs. e.g.
  returning `None`) when no secret is mounted and no
  `FLYTE_SECRETS_*`-prefixed env/file exists — `_client()`'s broad
  `except Exception` is defensive based on the documented behavior
  ("looks inside the task pod for an environment variable or a mounted
  file... " implying a lookup failure when neither exists) but the actual
  exception type was not observed directly, since `flytekit` isn't
  installed here to trigger it.
- `flytectl create secret ...` (the README's suggested setup command) was
  never run — no `flytectl` or live Flyte deployment available here.

## Steps (needs the account owner)

1. In an environment with normal network access:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -e ".[test]"
   pytest
   ```
2. Build and sanity-check the wheel's namespace-package layout:
   ```bash
   pip install build && python3 -m build
   python3 -c "import zipfile; zipfile.ZipFile('dist/flytekitplugins_anakin-0.1.0-py3-none-any.whl').printdir()"
   ```
   confirm there's no `flytekitplugins/__init__.py` entry but there is
   `flytekitplugins/anakin/__init__.py`.
3. Against a real (or local `flyte demo start`) Flyte cluster: create the
   `anakin`/`api-key` secret with a real Anakin API key, then
   `pyflyte run --remote example_workflows/example_anakin.py
   anakin_research_wf` end-to-end.
4. Push as `Anakin-Inc/flytekitplugins-anakin` (this repo's actual
   `origin`; `pyproject.toml`'s `Repository`/`Issues` URLs were corrected to
   match in `feat/full-tool-coverage`), publish to PyPI as
   `flytekitplugins-anakin`.
5. Optional, once live: open a PR to add a row to
   `flyteorg/flytekit`'s `plugins/README.md` plugin table (the doc says
   "it is not necessary to add plugins here, but this is a good starting
   place" — i.e. listing is for discoverability, not a requirement to
   function).

## Not done

Never installed or run against a real `flytekit` runtime or Flyte
deployment — verified by close reading against real, live-fetched Flyte
docs and a real reference plugin's source (`flytekit-openai`), `py_compile`
on all 6 source files, and the namespace-package directory shape confirmed
by hand. Treat as reviewed-but-unexecuted, same status as
`airflow-provider-anakin`, `langchain-anakin`, and `dagster-anakin` before
it.
