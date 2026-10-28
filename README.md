# flytekitplugins-anakin

Flyte tasks for [Anakin](https://anakin.io), a web data API. Scrape and crawl
sites to markdown, run AI web search and research, run pre-built Wire actions
on hundreds of sites, watch pages for changes, and drive an AI agent in a cloud
browser, all as typed tasks in your Flyte workflows.

Built on the official [`anakin-sdk`](https://pypi.org/project/anakin-sdk/)
Python client. Supports flytekit 1.14+ on Python 3.10 to 3.13. The tasks are
plain `@task` functions, so they run locally with `pyflyte run` and on any
Flyte cluster with no backend plugin or connector to deploy.

## Install

```bash
pip install flytekitplugins-anakin
```

Add it to the image your tasks run in, for example with `ImageSpec`:

```python
from flytekit import ImageSpec

image = ImageSpec(packages=["flytekitplugins-anakin"])
```

## Credentials

Get an API key at [anakin.io/dashboard](https://anakin.io/dashboard). The free
tier needs no card.

On a cluster, store it as a Flyte secret in group `anakin`, key `api-key`. The
tasks already request it:

```bash
kubectl create secret generic anakin --from-literal=api-key=ask_... -n <project>-<domain>
```

(Or `flytectl create secret` / your deployment's secret manager. See
[Flyte secrets](https://docs.flyte.org/en/latest/user_guide/productionizing/secrets.html).)

Locally, set `ANAKIN_API_KEY` instead. The tasks read the Flyte secret first,
then the environment variable. With no key at all, `scrape_url`,
`wire_discover`, `wire_catalogs` and `wire_catalog` still work on a small free
allowance, which is enough to try the package.

## Example

```python
import functools

from anakin.models import Document
from flytekit import map_task, task, workflow
from flytekitplugins.anakin import scrape_url, search


@task
def word_counts(docs: list[Document]) -> dict:
    return {doc.url: len((doc.markdown or "").split()) for doc in docs}


# map_task maps over `url` and needs every other input bound, defaults included.
scrape = functools.partial(
    scrape_url,
    country="us",
    use_browser=False,
    generate_json=False,
    output_schema=None,
    formats=None,
    force_fresh=False,
    session_id=None,
    session_name=None,
    poll_timeout=None,
)


@workflow
def pages(urls: list[str]) -> dict:
    docs = map_task(scrape)(url=urls)
    return word_counts(docs=docs)


@workflow
def news(topic: str) -> str:
    return search(prompt=f"{topic} news this week", limit=5).results[0].url
```

```bash
pyflyte run example.py pages --urls '["https://example.com", "https://anakin.io"]'
```

More in [`example_workflows/example_anakin.py`](example_workflows/example_anakin.py).

## Tasks

| Task | What it does | Output |
|---|---|---|
| `scrape_url` | Scrape a URL to markdown, optionally extract JSON with AI | `Document` |
| `map_site` | List the URLs on a site (sitemap plus link traversal) | `MapResult` |
| `crawl_site` | Fetch markdown for many pages of a site in one job | `CrawlResult` |
| `search` | AI web search with citations | `SearchResult` |
| `agentic_search` | Multi-step research returning a summary and structured data | `AgenticSearchResult` |
| `wire_discover` | Find Wire actions for a task described in plain language | `list[WireActionMatch]` |
| `wire_catalogs` | List every site in the Wire catalog | `list[WireCatalog]` |
| `wire_catalog` | One site's Wire actions and login fields | `WireCatalogDetail` |
| `wire_read_action` | Run a Wire action that reads data | `WireResult` |
| `wire_write_action` | Run a Wire action that changes state (form, cart, post) | `WireResult` |
| `wire_identities` | List saved Wire identities and their credentials | `list[WireIdentity]` |
| `wire_login` | Sign in to a site and get a `credential_id` | `WireLoginResult` |
| `wire_build` | Request a new Wire action for a site not in the catalog | `WireBuildRequest` |
| `wire_build_status` | Check a build request | `WireBuildRequest` |
| `monitor_create` | Create a scheduled website monitor (page, site or Wire) | `Monitor` |
| `monitor_list` / `monitor_get` | List monitors, or fetch one | `list[Monitor]` / `Monitor` |
| `monitor_changes` | A monitor's detected changes | `list[MonitorChange]` |
| `monitor_control` | Pause, resume, run now or delete a monitor | `dict` or `None` |
| `ai_visibility_sources` | AI answer engines available to `ai_visibility_search` | `list[AIVisibilitySource]` |
| `ai_visibility_search` | Ask several AI engines one question and compare answers | `AIVisibilitySearch` |
| `session_list` | List saved browser sessions (logged-in states) | `list[BrowserSession]` |
| `session_delete` | Delete a saved browser session | `None` |
| `browser_task` | Run a plain-language task in an AI-driven cloud browser | `dict` |

Outputs are `anakin.models` Pydantic models, which flytekit serializes
natively, so downstream tasks get typed objects (`doc.markdown`,
`result.data`). Free-form JSON inputs such as `params` and `output_schema` are
plain `dict`.

## Notes

- **Retries and caching.** The SDK already retries 429 and 5xx responses.
  Read tasks are safe to give Flyte `retries` or `cache=True` with
  `with_overrides` or your own wrapper. Don't do that for `wire_write_action`,
  `wire_login`, `wire_build` or `monitor_create`: repeating them repeats the
  write.
- **Payments.** `wire_write_action`, `wire_build` and `browser_task` refuse
  anything that looks like a payment or fund transfer, the same rule as
  Anakin's MCP server. Set `ANAKIN_ALLOW_FINANCIAL=true` to turn that off.
- **Secrets in outputs.** Flyte stores task inputs and outputs. Monitor
  outputs have their webhook signing secret redacted. Don't pass passwords to
  `wire_login` as literals from workflow code; read them from a Flyte secret
  inside a task, or use a 1Password `source_id`.
- **Base URL.** Set `ANAKIN_BASE_URL` to point at a non-production API.
- flytekit may log `Unsupported Type typing.Any found` on import. It comes
  from flytekit building attribute-access metadata for model fields typed
  `Any` (Wire `data`, for example); the outputs themselves are serialized as
  MessagePack, not pickle.

## Development

```bash
uv venv && uv pip install -e . --group test --group lint
uv run pytest
uv run ruff check . && uv run mypy flytekitplugins
ANAKIN_LIVE_TESTS=1 uv run pytest tests/test_live.py   # calls the live API
```

## License

Apache-2.0
