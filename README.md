# flytekitplugins-anakin

Flyte tasks for [Anakin](https://anakin.io) — web scraping, AI-powered
search, and multi-stage agentic research — built on the official
[`anakin-sdk`](https://github.com/Anakin-Inc/anakin-py) Python client (not a
separate HTTP implementation).

## Scope: plain `@task` functions, not a custom Task subclass

This package is **three `@task`-decorated Python functions**, not a custom
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
- Anakin's API is a plain synchronous HTTP call (`/search`) or a
  submit-and-poll call (`/url-scraper`, `/agentic-search`), and
  `anakin-sdk` already implements the HTTP, retry, and polling logic. A
  task body just calls the SDK client, exactly like any other Python
  function that happens to hit a network API. No custom container, no
  backend plugin, no cluster-side component required.

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

| Task | What it does |
|---|---|
| `scrape_url` | Scrape a URL to markdown (+ optional formats / AI-extracted JSON) |
| `search` | Synchronous AI-powered web search with citations |
| `agentic_search` | Multi-stage research: search, scrape citations, extract structured data with a summary |

```python
from flytekit import workflow
from flytekitplugins.anakin import scrape_url, search
from anakin.models import Document, SearchResult

@workflow
def my_wf() -> SearchResult:
    doc: Document = scrape_url(url="https://example.com")
    return search(prompt="latest AI agent news")
```

Each task returns the corresponding `anakin-sdk` Pydantic model
(`Document`, `SearchResult`, `AgenticSearchResult`) directly as its output
type — flytekit >= 1.14 natively serializes Pydantic v2 `BaseModel` task
outputs (MessagePack-encoded), so no manual `model_dump()` flattening is
needed.

See `example_workflows/example_anakin.py` for a full runnable example,
including `agentic_search`.

## Development

This package depends on `anakin-sdk` (live on PyPI) and `flytekit`.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
pytest
```

## License

Apache-2.0.
