# flytekitplugins-anakin

Flyte tasks for [Anakin](https://anakin.io) — web scraping, mapping,
crawling, AI-powered search and agentic research, Wire pre-built site
automation, website monitoring, AI visibility, browser sessions, and AI
browser automation. All 21 of Anakin's API capabilities, built on the
official [`anakin-sdk`](https://github.com/Anakin-Inc/anakin-py) Python
client where it already covers the endpoint, and direct REST calls
otherwise — see the task table below.

## Scope: plain `@task` functions, not a custom Task subclass

This package is **21 `@task`-decorated Python functions**, not a custom
`PythonTask` subclass or a Flyte backend connector. That's a deliberate
scope decision based on reading Flyte's own docs, not a shortcut:

- Flyte's task-plugins documentation states that a standard
  `@task`-decorated function wrapping a third-party API call requires no
  plugin machinery — "it's simply a normal Python function." Custom
  `PythonTask`/connector subclasses exist for cases needing custom
  serialization, remote execution semantics, or cluster-side infrastructure.
  For comparison, `flytekitplugins-openai`'s `ChatGPTTask` mixes in
  `SyncConnectorExecutorMixin` and needs a **connector service deployed on
  the Flyte cluster itself** to run — real infrastructure, appropriate for
  OpenAI's job model, not appropriate here.
- Every endpoint here is a plain synchronous HTTP call, a submit-and-poll
  call, or a plain CRUD call — nothing that needs custom serialization or
  cluster-side infrastructure. Where `anakin-sdk` already implements an
  endpoint, a task body just calls the SDK client. Where it doesn't (12 of
  the 21 — see the table below), a task body makes a direct `httpx` call
  using the same auth header and retry/poll behavior the SDK itself uses
  internally (`flytekitplugins/anakin/_http.py`). Either way: no custom
  container, no backend plugin, no cluster-side component required.

The package is still laid out as a `flytekitplugins.*` namespace-package
microlib per `flyteorg/flytekit`'s own plugin-authoring convention
(`plugins/README.md`) — so `pip install flytekitplugins-anakin` and
`from flytekitplugins.anakin import scrape_url` read exactly like any other
flytekit plugin. See `SUBMIT.md` for the full research trail and what was
and wasn't verified.

## Install

```bash
pip install -U flytekitplugins-anakin
```

## Auth

Tasks read the Anakin API key from Flyte's secret manager
(`group="anakin"`, `key="api-key"`) via
`flytekit.current_context().secrets.get(...)` — the documented Flyte
pattern for injecting credentials into a task without putting them in task
inputs or workflow code.

Create the secret before running against a real Flyte cluster, e.g.:

```bash
flytectl create secret --name api-key --group anakin --value ask-...
```

If no secret is mounted, tasks fall back to the `ANAKIN_API_KEY`
environment variable — the same fallback `anakin.Anakin()` itself
implements — so they also work with `pyflyte run` locally, no Flyte backend
or secret manager involved at all:

```bash
ANAKIN_API_KEY=ask-... pyflyte run example_workflows/example_anakin.py anakin_research_wf
```

## Tasks

| Task | What it does | Implementation |
|---|---|---|
| `scrape_url` | Scrape a URL to markdown (+ optional formats / AI-extracted JSON) | `anakin-sdk` (`Anakin.scrape`) |
| `search` | Synchronous AI-powered web search with citations | `anakin-sdk` (`Anakin.search`) |
| `agentic_search` | Multi-stage research: search, scrape citations, extract structured data with a summary | `anakin-sdk` (`Anakin.agentic_search`) |
| `map_site` | Discover all reachable URLs under a site (sitemap + link traversal) | `anakin-sdk` (`Anakin.map`) |
| `crawl_site` | Bulk-fetch markdown across a site (catalog ingestion, RAG corpus) | `anakin-sdk` (`Anakin.crawl`) |
| `wire_read_action` | Run a Wire pre-built READ action (extracts data, e.g. product price/specs) | `anakin-sdk` (`Anakin.wire`) |
| `wire_write_action` | Run a Wire pre-built WRITE action (state-changing, e.g. submit a form) | `anakin-sdk` (`Anakin.wire`) |
| `wire_discover` | Find Wire actions for a task from a natural-language intent | raw HTTP (`GET /wire/resolve`) |
| `wire_catalog` | Browse the Wire catalog, or one site's full action list | raw HTTP (`GET /wire/catalog[/:slug]`) |
| `wire_identities` | List your saved Wire identities and credentials | raw HTTP (`GET /wire/identities`) |
| `wire_login` | Sign in to a credentials-mode Wire site, get a `credential_id` | raw HTTP (`POST /wire/login`) |
| `wire_build` | Request a brand-new Wire action for an uncatalogued site | raw HTTP (`POST /wire/build-request`) |
| `session_list` | List saved browser sessions (encrypted login state) | `anakin-sdk` (`Anakin.sessions.list`) |
| `session_delete` | Permanently delete a saved browser session | `anakin-sdk` (`Anakin.sessions.delete`) |
| `monitor_create` | Create a scheduled website monitor (page/site/Wire scope) | raw HTTP (`POST /monitors`) |
| `monitor_list` | List monitors, or fetch one by id | raw HTTP (`GET /monitors[/:id]`) |
| `monitor_changes` | Get a monitor's detected changes | raw HTTP (`GET /monitors/:id/changes`) |
| `monitor_control` | Pause / resume / run-now / delete a monitor | raw HTTP (`POST .../{pause,resume,run}`, `DELETE`) |
| `ai_visibility_sources` | List AI answer engines available to `ai_visibility_search` | raw HTTP (`GET /ai-visibility/sources`) |
| `ai_visibility_search` | Ask multiple AI engines (ChatGPT, Gemini, ...) the same question, compare answers | raw HTTP (`POST /ai-visibility/search` + poll) |
| `browser_task` | Run a natural-language task in a real AI-driven cloud browser | raw HTTP (`POST /ai/evaluate` + poll) |

"raw HTTP" tasks call the REST API directly via `httpx` (see
`flytekitplugins/anakin/_http.py`) because `anakin-sdk` v0.1.0 doesn't
implement those 12 endpoints yet — confirmed by reading
`anakin-py/src/anakin/client.py` in full, not assumed. Ground truth for
every one of those endpoints (path, verb, request/response shape, polling
target) is `anakin-mcp/src/client.ts`, Anakin's own MCP server — a second,
independent implementation against the same REST API.

```python
from flytekit import workflow
from flytekitplugins.anakin import scrape_url, search, wire_discover
from anakin.models import Document, SearchResult

@workflow
def my_wf() -> SearchResult:
    doc: Document = scrape_url(url="https://example.com")
    candidates = wire_discover(q="top phones on walmart")
    return search(prompt="latest AI agent news")
```

Tasks backed by `anakin-sdk` return the SDK's Pydantic model
(`Document`, `SearchResult`, `AgenticSearchResult`, `MapResult`,
`CrawlResult`, `WireResult`, `list[BrowserSession]`) directly as their
output type — flytekit >= 1.14 natively serializes Pydantic v2 `BaseModel`
task outputs (MessagePack-encoded), so no manual `model_dump()` flattening
is needed. Raw-HTTP tasks (no corresponding SDK model exists yet) return
`dict[str, Any]` — the API's JSON response, normalized to a dict.

See `example_workflows/example_anakin.py` for full runnable examples,
including the original research pipeline plus a second workflow exercising
Wire discovery, website monitoring, and AI visibility.

## A note on Wire auth (`credential_id`)

`anakin-sdk` v0.1.0's `Anakin.wire()` does not yet accept `credential_id` /
`identity_id`, even though the REST API supports both for auth-required
actions (confirmed by reading `anakin-py/src/anakin/client.py` in full).
`wire_read_action` / `wire_write_action` in this package inherit that
limitation — actions with `auth_mode="required"` will raise
`WireAuthRequiredError` until the SDK adds the parameter. Use
`wire_identities` / `wire_login` to obtain a `credential_id` today; it can
be threaded through once `anakin-sdk` exposes it on `wire()`.

## Development

This package depends on `anakin-sdk` (live on PyPI), `flytekit`, and
`httpx` (used directly by `_http.py` for the 12 endpoints not yet in
`anakin-sdk`).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
pytest
```

## License

Apache-2.0.
