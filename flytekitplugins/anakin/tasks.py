"""Flyte tasks for the Anakin API (https://api.anakin.io/v1).

These are plain ``@task``-decorated functions, not a custom ``PythonTask``
subclass or backend connector. That is a deliberate, research-backed scope
decision, not a shortcut:

- Flyte's own "Task plugins" documentation states that a standard
  ``@task``-decorated function wrapping a third-party API call "requires no
  plugin machinery... it's simply a normal Python function." Custom
  ``PythonTask``/connector subclasses (e.g. ``flytekitplugins-openai``'s
  ``ChatGPTTask``, which mixes in ``SyncConnectorExecutorMixin`` and requires
  a *backend* connector service deployed on the Flyte cluster) exist for
  cases needing custom serialization, remote execution semantics, or
  cluster-side infrastructure — none of which apply here. Anakin's API is a
  plain synchronous HTTP call (``/search``) or submit-and-poll call
  (``/url-scraper``, ``/agentic-search``), and ``anakin-sdk`` already does
  the HTTP/retry/polling work; a task body just calls it, exactly like any
  other Python function that happens to hit a network API.
- The package is still laid out as a namespace-package ``flytekitplugins.*``
  microlib per ``flyteorg/flytekit``'s own plugin-authoring guidelines
  (`plugins/README.md`), so ``pip install flytekitplugins-anakin`` and
  ``from flytekitplugins.anakin import scrape_url`` read exactly like any
  other flytekit plugin. The ``entry_points={"flytekit.plugins": ...}``
  auto-load hook those guidelines mention is explicitly documented as
  optional — "for plugins where auto-loading on installation is desirable"
  such as type/data plugins that must register themselves as a side effect
  of import (e.g. ``TypeEngine.register(...)``). Nothing here needs that:
  these tasks are used the normal way, by importing them into a workflow.

Auth: the Anakin API key is read from Flyte's secret manager via
``secret_requests`` + ``current_context().secrets.get(...)`` — the
documented Flyte pattern for injecting credentials into a task without
putting them in task inputs or workflow code
(see ``docs/user_guide/productionizing/secrets.md`` in flyteorg/flyte).
Falls back to the ``ANAKIN_API_KEY`` environment variable — the same
fallback ``anakin.Anakin()`` itself implements — when no secret is mounted,
so these tasks also work with ``pyflyte run`` locally with no Flyte backend
or secret manager involved at all.
"""

from __future__ import annotations

from typing import Any, Optional

from flytekit import Secret, current_context, task

from anakin import Anakin
from anakin.models import AgenticSearchResult, Document, SearchResult

#: Secret group/key Flyte tasks in this module request. Create the secret
#: with e.g. ``flytectl create secret --name api-key --group anakin
#: --value ask-...`` (or your Flyte deployment's equivalent) before running
#: these tasks against a real cluster.
ANAKIN_SECRET_GROUP = "anakin"
ANAKIN_SECRET_KEY = "api-key"

DEFAULT_ANAKIN_BASE_URL = "https://api.anakin.io/v1"

_ANAKIN_SECRET_REQUEST = Secret(group=ANAKIN_SECRET_GROUP, key=ANAKIN_SECRET_KEY)


def _client(base_url: str) -> Anakin:
    """Build an ``anakin.Anakin`` SDK client for the current task execution.

    Tries Flyte's secret manager first; falls through to
    ``anakin.Anakin()``'s own ``ANAKIN_API_KEY`` env var fallback if no
    secret is mounted (e.g. local ``pyflyte run``, or a cluster where the
    key is injected as a plain env var instead of a Flyte-managed secret).
    """
    api_key: Optional[str] = None
    try:
        api_key = current_context().secrets.get(ANAKIN_SECRET_GROUP, ANAKIN_SECRET_KEY)
    except Exception:
        api_key = None
    return Anakin(api_key=api_key, base_url=base_url)


# ─── url-scraper ────────────────────────────────────────────────────────────


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def scrape_url(
    url: str,
    country: str = "us",
    use_browser: bool = False,
    generate_json: bool = False,
    force_fresh: bool = False,
    session_id: Optional[str] = None,
    session_name: Optional[str] = None,
    poll_timeout: Optional[float] = None,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> Document:
    """Scrape a single URL via Anakin.

    Submits ``POST /url-scraper`` and polls ``GET /url-scraper/:jobId``
    until the job reaches a terminal state (handled inside ``anakin-sdk``,
    not reimplemented here). Returns the SDK's ``Document`` model directly —
    flytekit >= 1.14 natively serializes Pydantic v2 ``BaseModel`` task
    outputs (MessagePack-encoded), so no manual ``model_dump()`` flattening
    is needed the way an Airflow XCom backend would require.

    :param url: The URL to scrape.
    :param country: Proxy country code, e.g. ``"us"``, ``"gb"``, ``"de"``.
    :param use_browser: Use a headless browser — needed for JS-heavy sites.
    :param generate_json: AI-extract structured JSON from the page content.
    :param force_fresh: Bypass the cache and force a fresh extraction.
    :param session_id: Reuse an existing authenticated browser session.
    :param session_name: Name for a new session when ``session_id`` is unset.
    :param poll_timeout: Seconds to wait for the job to finish; falls back
        to the SDK client's own default (300s) when unset.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    client = _client(base_url)
    return client.scrape(
        url,
        country=country,
        use_browser=use_browser,
        generate_json=generate_json,
        force_fresh=force_fresh,
        session_id=session_id,
        session_name=session_name,
        poll_timeout=poll_timeout,
    )


# ─── search (synchronous) ───────────────────────────────────────────────────


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def search(
    prompt: str,
    limit: int = 5,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> SearchResult:
    """AI-powered web search via Anakin — synchronous, no polling.

    Submits ``POST /search`` and returns immediately. Costs 3 credits per
    call per the Anakin API contract.

    :param prompt: The search query or question.
    :param limit: Maximum number of results to return (default 5).
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    client = _client(base_url)
    return client.search(prompt, limit=limit)


# ─── agentic-search ─────────────────────────────────────────────────────────


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def agentic_search(
    prompt: str,
    use_browser: bool = True,
    schema: Optional[dict[str, Any]] = None,
    poll_timeout: Optional[float] = None,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> AgenticSearchResult:
    """Multi-stage AI research pipeline via Anakin: search, scrape citation
    sources, and extract structured data with a summary.

    Submits ``POST /agentic-search`` and polls ``GET /agentic-search/:jobId``
    until terminal. Slower than :func:`search` (can take minutes) and costs
    10 credits per call.

    :param prompt: The research question or topic (max 8KB).
    :param use_browser: Use a headless browser for citation scraping.
        Defaults to ``True`` — matches the ``anakin-sdk`` client default
        (note this is the opposite default from :func:`scrape_url`'s
        ``use_browser=False`` — preserved here rather than flattened to one
        default, per ``anakin-py/src/anakin/client.py``).
    :param schema: Optional JSON Schema (max 50KB) constraining the
        structured output. Leave unset to let the pipeline choose its own.
    :param poll_timeout: Seconds to wait for the job to finish; falls back
        to the SDK client's own default (300s) when unset.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    client = _client(base_url)
    return client.agentic_search(
        prompt,
        use_browser=use_browser,
        schema=schema,
        poll_timeout=poll_timeout,
    )
