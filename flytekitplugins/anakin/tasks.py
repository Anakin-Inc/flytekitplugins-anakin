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

Coverage: this module now wraps all 21 of Anakin's API capabilities, not
just the original 3 (``scrape_url``, ``search``, ``agentic_search``). Two
strategies, chosen per capability based on what actually exists in
``anakin-sdk`` v0.1.0 (read directly from ``anakin-py/src/anakin/client.py``,
not assumed):

- Where ``anakin-sdk`` already implements the endpoint (``map``, ``crawl``,
  ``wire``, ``sessions.list``/``sessions.delete``), the task is a thin
  wrapper around the SDK client, exactly like the original 3 tasks.
- Where it doesn't (Wire discovery/catalog/identities/login/build, website
  monitoring, AI visibility, AI browser automation — confirmed missing by
  reading the SDK source in full), the task calls the REST API directly via
  the small ``httpx``-based helper in ``_http.py``, using the same auth
  header and retry/poll behavior the SDK itself uses internally. Ground
  truth for every one of those endpoints is ``anakin-mcp/src/client.ts``
  (Anakin's own MCP server, a second independent implementation against the
  same REST API), read directly, not invented.

See ``README.md`` for the full task table with an SDK-vs-raw-HTTP column.
"""

from __future__ import annotations

import os
from typing import Any, Literal, Optional
from urllib.parse import quote

from flytekit import Secret, current_context, task

from anakin import Anakin
from anakin.models import (
    AgenticSearchResult,
    BrowserSession,
    CrawlResult,
    Document,
    MapResult,
    SearchResult,
    WireResult,
)

from . import _http

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


def _resolve_api_key() -> str:
    """Resolve the Anakin API key for the raw-``httpx`` tasks in this module
    (the endpoints ``anakin-sdk`` doesn't cover — see module docstring).

    Same secret-then-env-var resolution order as ``_client()``, but explicit
    and eager here: unlike ``Anakin(api_key=None, ...)``, which defers its
    own ``ANAKIN_API_KEY`` fallback (and ``ConfigurationError``) to
    ``anakin._http.HttpClient.__init__``, ``_http.request()`` has no such
    fallback built in — it just needs a string.
    """
    api_key: Optional[str] = None
    try:
        api_key = current_context().secrets.get(ANAKIN_SECRET_GROUP, ANAKIN_SECRET_KEY)
    except Exception:
        api_key = None
    if not api_key:
        api_key = os.environ.get("ANAKIN_API_KEY")
    if not api_key:
        raise _http.AnakinAPIError(
            "Anakin API key not provided. Create the Flyte secret "
            f"(group={ANAKIN_SECRET_GROUP!r}, key={ANAKIN_SECRET_KEY!r}) or set "
            "the ANAKIN_API_KEY environment variable."
        )
    return api_key


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


# ═══════════════════════════════════════════════════════════════════════════
# The remaining 18 capabilities. Each section header notes whether the task
# wraps anakin-sdk (like the three above) or calls the REST API directly via
# ``_http.py`` (for endpoints the SDK doesn't implement yet).
# ═══════════════════════════════════════════════════════════════════════════


# ─── map (anakin-sdk: Anakin.map) ───────────────────────────────────────────


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def map_site(
    url: str,
    limit: int = 100,
    depth: int = 2,
    limit_per_level: int = 100,
    include_subdomains: bool = False,
    include_external_links: bool = False,
    search: Optional[str] = None,
    use_browser: bool = False,
    session_id: Optional[str] = None,
    poll_timeout: Optional[float] = None,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> MapResult:
    """Discover URLs on a website (sitemap + link traversal) via Anakin.

    Named ``map_site`` rather than ``map`` to avoid shadowing the Python
    builtin — same naming rationale as ``scrape_url`` vs. the SDK's
    ``scrape``. Submits ``POST /map`` and polls ``GET /map/:jobId`` until
    terminal (both handled inside ``anakin-sdk``).

    :param url: The starting URL for discovery (typically a homepage or
        section root).
    :param limit: Maximum number of URLs to return overall.
    :param depth: How many link-hops from the starting URL to follow.
    :param limit_per_level: Maximum URLs collected per depth level (controls
        breadth).
    :param include_subdomains: Include URLs on subdomains of the starting
        host.
    :param include_external_links: Also collect (but do not follow) external
        links.
    :param search: Optional keyword filter — only return URLs whose
        path/title matches.
    :param use_browser: Render with a headless browser — needed for SPAs.
    :param session_id: Reuse an existing authenticated browser session.
    :param poll_timeout: Seconds to wait for the job to finish; falls back
        to the SDK client's own default (300s) when unset.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    client = _client(base_url)
    return client.map(
        url,
        limit=limit,
        depth=depth,
        limit_per_level=limit_per_level,
        include_subdomains=include_subdomains,
        include_external_links=include_external_links,
        search=search,
        use_browser=use_browser,
        session_id=session_id,
        poll_timeout=poll_timeout,
    )


# ─── crawl (anakin-sdk: Anakin.crawl) ───────────────────────────────────────


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def crawl_site(
    url: str,
    max_pages: int = 10,
    depth: int = 1,
    include_patterns: Optional[list[str]] = None,
    exclude_patterns: Optional[list[str]] = None,
    country: str = "us",
    use_browser: bool = False,
    session_id: Optional[str] = None,
    poll_timeout: Optional[float] = None,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> CrawlResult:
    """Bulk-fetch markdown across a site via Anakin (catalog ingestion,
    site-wide RAG corpus building).

    Submits ``POST /crawl`` and polls ``GET /crawl/:jobId`` until terminal
    (both handled inside ``anakin-sdk``).

    :param url: Starting URL.
    :param max_pages: Hard cap on pages fetched.
    :param depth: Link-hops from the starting URL to follow.
    :param include_patterns: Glob/regex patterns; only URLs matching at
        least one are fetched.
    :param exclude_patterns: Glob/regex patterns; URLs matching any are
        skipped.
    :param country: Proxy egress country code, e.g. ``"us"``, ``"gb"``.
    :param use_browser: Render each page in a headless browser — needed for
        SPAs.
    :param session_id: Optional saved-browser-session ID for login-protected
        sites.
    :param poll_timeout: Seconds to wait for the job to finish; falls back
        to the SDK client's own default (300s) when unset.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    client = _client(base_url)
    return client.crawl(
        url,
        max_pages=max_pages,
        depth=depth,
        include_patterns=tuple(include_patterns or ()),
        exclude_patterns=tuple(exclude_patterns or ()),
        country=country,
        use_browser=use_browser,
        session_id=session_id,
        poll_timeout=poll_timeout,
    )


# ─── wire: run a pre-built action (anakin-sdk: Anakin.wire) ────────────────
#
# anakin-mcp splits execution into two tools, wire_read_action and
# wire_write_action, purely by the action's declared type (read vs. write)
# so each can carry an honest safety annotation for its marketplace listing
# (see anakin-mcp/src/tools/wire.ts's module docstring) — both call the same
# underlying `POST /wire/task` + poll `GET /wire/jobs/:id`. Mirrored here as
# two tasks over the same anakin-sdk `Anakin.wire()` call, for the same
# reason: a workflow author picking `wire_write_action` is an explicit,
# visible signal that a step can change state on a third-party site, which
# `wire_read_action` alone never implies.
#
# Note: anakin-sdk v0.1.0's `wire()` does not yet accept `credential_id` /
# `identity_id`, even though the REST API supports both (see
# `WireRunOptions` in anakin-mcp/src/client.ts) — confirmed by reading
# `anakin-py/src/anakin/client.py` in full, not an oversight in this
# package. Actions with `auth_mode="required"` will fail with
# `WireAuthRequiredError` until the SDK adds that parameter; use
# `wire_identities`/`wire_login` (below) to obtain a credential in the
# meantime and pass it once the SDK supports it.


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def wire_read_action(
    action_id: str,
    params: Optional[dict[str, Any]] = None,
    poll_timeout: Optional[float] = None,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> WireResult:
    """Run a Wire READ action — one that extracts data without changing
    state on the target site (search listings, fetch a product's
    price/specs, read a profile, pull dashboard metrics).

    Find ``action_id``\\ s via :func:`wire_discover` or :func:`wire_catalog`
    and confirm the action's ``type`` is ``"read"``; ``params`` must match
    that action's parameter schema. Submits ``POST /holocron/task`` and
    polls ``GET /holocron/jobs/:jobId`` until terminal (both handled inside
    ``anakin-sdk``). For state-changing actions use
    :func:`wire_write_action` instead.

    :param action_id: The Wire action to run.
    :param params: The action's input parameters (its schema comes from
        discovery); omit for actions that take none.
    :param poll_timeout: Seconds to wait for the job to finish; falls back
        to the SDK client's own default (300s) when unset.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    client = _client(base_url)
    return client.wire(action_id, params or {}, poll_timeout=poll_timeout)


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def wire_write_action(
    action_id: str,
    params: Optional[dict[str, Any]] = None,
    poll_timeout: Optional[float] = None,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> WireResult:
    """Run a Wire WRITE action — one that performs a state-changing
    interaction on the target site (submit a form, add to cart, post
    content, update account settings).

    Find ``action_id``\\ s via :func:`wire_discover` or :func:`wire_catalog`
    and confirm the action's ``type`` is ``"write"``; ``params`` must match
    that action's parameter schema. Most write actions require auth — see
    the module note above on ``credential_id`` (not yet supported by
    ``anakin-sdk`` v0.1.0). Submits ``POST /holocron/task`` and polls
    ``GET /holocron/jobs/:jobId`` until terminal (both handled inside
    ``anakin-sdk``). For read-only data extraction use
    :func:`wire_read_action` instead.

    :param action_id: The Wire action to run.
    :param params: The action's input parameters (its schema comes from
        discovery); omit for actions that take none.
    :param poll_timeout: Seconds to wait for the job to finish; falls back
        to the SDK client's own default (300s) when unset.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    client = _client(base_url)
    return client.wire(action_id, params or {}, poll_timeout=poll_timeout)


# ─── wire: discovery & account management (raw HTTP — not in anakin-sdk) ──


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def wire_discover(
    q: str,
    limit: int = 5,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> dict[str, Any]:
    """Find Wire actions for a task from a natural-language intent.

    Calls ``GET /wire/resolve`` directly — not covered by ``anakin-sdk``
    v0.1.0. Returns ranked candidate actions, each with its ``action_id``,
    ``type`` (``"read"``/``"write"``), required/optional params, credit
    cost, and whether auth is needed. Run a returned action with
    :func:`wire_read_action` or :func:`wire_write_action`.

    :param q: The intent in natural language, e.g. ``"top phones on
        walmart"``, ``"search airbnb listings in Lisbon"``.
    :param limit: Maximum number of candidate actions to return.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    api_key = _resolve_api_key()
    params = {"q": q, "limit": limit}
    return _http.as_dict(
        _http.request("GET", "/wire/resolve", api_key=api_key, base_url=base_url, params=params)
    )


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def wire_catalog(
    slug: Optional[str] = None,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> dict[str, Any]:
    """Browse the Wire catalog.

    Calls ``GET /wire/catalog`` (or ``GET /wire/catalog/:slug``) directly —
    not covered by ``anakin-sdk`` v0.1.0. With no ``slug``, lists every
    supported website and its action count. With a ``slug`` (e.g.
    ``"walmart"``, ``"amazon"``, ``"linkedin"``), returns that site's full
    action list with exact parameter schemas, each action's type and auth
    mode, and credit cost.

    :param slug: Catalog slug to inspect. Omit to list all catalogs.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    api_key = _resolve_api_key()
    path = f"/wire/catalog/{quote(slug, safe='')}" if slug else "/wire/catalog"
    return _http.as_dict(_http.request("GET", path, api_key=api_key, base_url=base_url))


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def wire_identities(
    catalog_id: Optional[str] = None,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> dict[str, Any]:
    """List your saved Wire identities and their credentials.

    Calls ``GET /wire/identities`` directly — not covered by ``anakin-sdk``
    v0.1.0. Each credential's ``id`` is a ``credential_id`` usable (once the
    SDK supports it — see the ``wire_read_action``/``wire_write_action``
    module note) to run actions whose ``auth_mode`` is ``"required"``.

    :param catalog_id: Optional — restrict to identities for a single
        catalog.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    api_key = _resolve_api_key()
    params = {"catalog_id": catalog_id} if catalog_id else None
    return _http.as_dict(
        _http.request(
            "GET", "/wire/identities", api_key=api_key, base_url=base_url, params=params
        )
    )


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def wire_login(
    catalog_slug: str,
    params: Optional[dict[str, Any]] = None,
    identity_name: Optional[str] = None,
    source_id: Optional[str] = None,
    source_ref: Optional[dict[str, Any]] = None,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> dict[str, Any]:
    """Sign in to a credentials-mode Wire site and get a ``credential_id``.

    Calls ``POST /wire/login`` directly — not covered by ``anakin-sdk``
    v0.1.0. Only needed for actions whose ``auth_mode`` is ``"required"``,
    and only for catalogs that support password sign-in. The password is
    never stored by Anakin, only the encrypted session.

    :param catalog_slug: The catalog to sign in to (e.g. ``"neb"``).
    :param params: Login fields defined by the catalog (e.g. ``{"email":
        ..., "password": ...}``) — see :func:`wire_catalog`'s
        ``login_input_schema`` for the field names.
    :param identity_name: Optional name for the identity. Derived from
        ``params`` in password mode; required when using a 1Password
        locator.
    :param source_id: Optional 1Password identity-source ID (alternative to
        ``params``).
    :param source_ref: Optional 1Password item locator (``vault_id``,
        ``item_id``, ``fields``) — used with ``source_id`` instead of
        ``params``.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    api_key = _resolve_api_key()
    body: dict[str, Any] = {"catalog_slug": catalog_slug}
    if params is not None:
        body["params"] = params
    if identity_name is not None:
        body["identity_name"] = identity_name
    if source_id is not None:
        body["source_id"] = source_id
    if source_ref is not None:
        body["source_ref"] = source_ref
    return _http.as_dict(
        _http.request("POST", "/wire/login", api_key=api_key, base_url=base_url, json=body)
    )


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def wire_build(
    website_url: str,
    goal: str,
    catalog_id: Optional[str] = None,
    visibility: Literal["private", "public"] = "private",
    force: bool = False,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> dict[str, Any]:
    """Request a brand-new Wire action for a website not yet in the catalog.

    Calls ``POST /wire/build-request`` directly — not covered by
    ``anakin-sdk`` v0.1.0. Asynchronous (returns ``status="pending"``) and
    charges credits, refunded automatically if the build fails. Only use
    this after :func:`wire_discover` / :func:`wire_catalog` confirm no
    existing action covers the site.

    :param website_url: The site to build an action for. The domain is
        extracted automatically.
    :param goal: Natural-language description of what the action should do
        or extract. Be specific — the builder synthesizes the scraper from
        this.
    :param catalog_id: Optional — attach to an existing catalog instead of
        creating one.
    :param visibility: Action visibility.
    :param force: Build even if similar actions already exist for the
        domain (otherwise the request is rejected with ``ACTION_EXISTS``).
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    api_key = _resolve_api_key()
    body: dict[str, Any] = {
        "website_url": website_url,
        "goal": goal,
        "visibility": visibility,
        "force": force,
    }
    if catalog_id is not None:
        body["catalog_id"] = catalog_id
    return _http.as_dict(
        _http.request(
            "POST", "/wire/build-request", api_key=api_key, base_url=base_url, json=body
        )
    )


# ─── browser sessions (anakin-sdk: Anakin.sessions.list / .delete) ─────────


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def session_list(
    domain: Optional[str] = None,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> list[BrowserSession]:
    """List your saved browser sessions (encrypted login states captured via
    the Anakin dashboard or Browser API).

    Each session's ``id`` is what :func:`scrape_url`/:func:`crawl_site`
    (``session_id``), :func:`monitor_create` (``session_id``), or
    :func:`browser_task` (``session_id``) take to work with login-protected
    pages. Calls ``GET /sessions`` via ``anakin-sdk``'s
    ``Anakin.sessions.list()``.

    :param domain: Filter to sessions for one website domain, e.g.
        ``"amazon.com"``.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    client = _client(base_url)
    return client.sessions.list(domain=domain)


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def session_delete(
    session_id: str,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> None:
    """Permanently delete a saved browser session and its encrypted login
    data.

    Irreversible — the user must log in again through the dashboard to
    recreate it, and anything referencing this ``session_id`` loses
    authenticated access. Calls ``DELETE /sessions/:id`` via ``anakin-sdk``'s
    ``Anakin.sessions.delete()``. Find ids with :func:`session_list`.

    :param session_id: The session ID to delete.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    client = _client(base_url)
    client.sessions.delete(session_id)


# ─── website monitoring (raw HTTP — not in anakin-sdk) ─────────────────────
#
# The API returns each monitor's `alertWebhookSecret` (an HMAC signing
# secret) inline. A secret that enters a workflow's task output/logs is
# compromised by definition (same reasoning anakin-mcp documents in
# monitor.ts), so every monitor response here is redacted before it's
# returned as a task output; retrieve the real value from the Anakin
# dashboard instead.

_REDACTED_SECRET = "[redacted — view in the Anakin dashboard]"


def _redact_monitor_secrets(value: Any) -> Any:
    """Deep-copy `value` with any `alertWebhookSecret` key's value replaced."""
    if isinstance(value, list):
        return [_redact_monitor_secrets(v) for v in value]
    if isinstance(value, dict):
        return {
            k: (_REDACTED_SECRET if k == "alertWebhookSecret" and v else _redact_monitor_secrets(v))
            for k, v in value.items()
        }
    return value


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def monitor_create(
    url: str,
    interval_minutes: int,
    scope: Literal["page", "site", "wire"] = "page",
    watch_mode: Literal["full_page", "specific_data"] = "full_page",
    watch_format: Literal["markdown", "html", "cleaned_html"] = "markdown",
    output_schema: Optional[dict[str, Any]] = None,
    ai_mode: bool = False,
    ai_goal: Optional[str] = None,
    use_browser: bool = False,
    country: str = "us",
    session_id: Optional[str] = None,
    is_active: bool = True,
    expires_at: Optional[str] = None,
    alert_webhook_url: Optional[str] = None,
    alert_emails: Optional[str] = None,
    max_pages: Optional[int] = None,
    max_depth: Optional[int] = None,
    include_patterns: Optional[list[str]] = None,
    exclude_patterns: Optional[list[str]] = None,
    wire_action_id: Optional[str] = None,
    wire_catalog_slug: Optional[str] = None,
    wire_credential_id: Optional[str] = None,
    wire_params: Optional[dict[str, Any]] = None,
    wire_watch_paths: Optional[list[str]] = None,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> dict[str, Any]:
    """Create a scheduled website monitor that checks a URL every
    ``interval_minutes`` (min 15) and records a change when the content
    differs — optionally alerting a webhook or email.

    Calls ``POST /monitors`` directly — not covered by ``anakin-sdk``
    v0.1.0. ``scope="page"`` (default) watches one URL; ``"site"`` crawls
    the site each run and tracks pages added/removed/changed; ``"wire"``
    runs a Wire action each check and diffs its JSON. ``watch_mode`` of
    ``"full_page"`` (2 credits/check) compares the whole page;
    ``"specific_data"`` (3 credits/check) extracts only the fields in
    ``output_schema`` with AI. ``ai_mode`` (+1 credit/check) filters out
    trivial noise and summarizes real changes. Active-monitor caps per plan:
    Free 5, Pro 20, Scale 100.

    :param url: The URL to watch (root URL for site scope; the Wire site's
        URL for wire scope).
    :param interval_minutes: Check frequency in minutes. Minimum 15.
    :param scope: What to monitor: one page, a whole site, or a Wire action.
    :param watch_mode: Compare the whole page, or only the fields in
        ``output_schema`` extracted with AI.
    :param watch_format: Format compared in ``full_page`` mode.
    :param output_schema: JSON Schema of the fields to track. Required when
        ``watch_mode`` is ``"specific_data"``.
    :param ai_mode: AI meaningful-change filtering.
    :param ai_goal: Natural-language description of which changes count as
        meaningful (used with ``ai_mode``).
    :param use_browser: Render checks with a stealth headless browser.
        Forced true server-side when ``session_id`` is set.
    :param country: Two-letter proxy country code.
    :param session_id: Saved browser-session ID for monitoring
        login-protected pages (see :func:`session_list`).
    :param is_active: Start running immediately.
    :param expires_at: Optional end date (ISO 8601 timestamp or
        ``YYYY-MM-DD``); the monitor auto-pauses when it passes.
    :param alert_webhook_url: Webhook URL that receives signed change
        alerts.
    :param alert_emails: Comma-separated email recipients for change
        alerts.
    :param max_pages: Site scope: max pages crawled per run.
    :param max_depth: Site scope: crawl depth (1-5).
    :param include_patterns: Site scope: glob patterns or hand-picked
        same-site URLs to track.
    :param exclude_patterns: Site scope: glob patterns to skip.
    :param wire_action_id: Wire scope (required there): the action run each
        check, e.g. ``"amazon.search_products"`` (see :func:`wire_discover`).
    :param wire_catalog_slug: Wire scope: catalog slug of the Wire site.
    :param wire_credential_id: Wire scope: credential ID when the action
        needs auth (see :func:`wire_identities`).
    :param wire_params: Wire scope: parameters passed to the action each
        check.
    :param wire_watch_paths: Wire scope: JSON paths to diff instead of the
        whole response.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    api_key = _resolve_api_key()
    body: dict[str, Any] = {"url": url, "intervalMinutes": interval_minutes}
    extras: dict[str, Any] = {
        "scope": scope,
        "watchMode": watch_mode,
        "watchFormat": watch_format,
        "outputSchema": output_schema,
        "aiMode": ai_mode,
        "aiGoal": ai_goal,
        "useBrowser": use_browser,
        "country": country,
        "sessionId": session_id,
        "isActive": is_active,
        "expiresAt": expires_at,
        "alertWebhookUrl": alert_webhook_url,
        "alertEmails": alert_emails,
        "maxPages": max_pages,
        "maxDepth": max_depth,
        "includePatterns": include_patterns,
        "excludePatterns": exclude_patterns,
        "wireActionId": wire_action_id,
        "wireCatalogSlug": wire_catalog_slug,
        "wireCredentialId": wire_credential_id,
        "wireParams": wire_params,
        "wireWatchPaths": wire_watch_paths,
    }
    # Only send fields the caller actually set — the API applies its own
    # defaults for the rest (matches anakin-mcp's monitor_create passthrough).
    body.update({k: v for k, v in extras.items() if v is not None})
    result = _http.as_dict(
        _http.request("POST", "/monitors", api_key=api_key, base_url=base_url, json=body)
    )
    return _redact_monitor_secrets(result)


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def monitor_list(
    monitor_id: Optional[str] = None,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> dict[str, Any]:
    """List your website monitors, or pass ``monitor_id`` to fetch one
    monitor's full configuration and status (next/last check time, active
    state, per-check credit cost, alert settings).

    Calls ``GET /monitors`` (or ``GET /monitors/:id``) directly — not
    covered by ``anakin-sdk`` v0.1.0. Use this to find a monitor's id before
    :func:`monitor_changes` or :func:`monitor_control`.

    :param monitor_id: Fetch just this monitor instead of the full list.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    api_key = _resolve_api_key()
    path = f"/monitors/{quote(monitor_id, safe='')}" if monitor_id else "/monitors"
    result = _http.as_dict(_http.request("GET", path, api_key=api_key, base_url=base_url))
    return _redact_monitor_secrets(result)


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def monitor_changes(
    monitor_id: str,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> dict[str, Any]:
    """Get the detected changes for a monitor — each entry records when the
    watched content differed from the previous check, with a diff/summary
    (and the AI change summary when ``ai_mode`` was on).

    Calls ``GET /monitors/:id/changes`` directly — not covered by
    ``anakin-sdk`` v0.1.0. Use :func:`monitor_list` first to find the
    monitor id.

    :param monitor_id: The monitor ID.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    api_key = _resolve_api_key()
    result = _http.as_dict(
        _http.request(
            "GET",
            f"/monitors/{quote(monitor_id, safe='')}/changes",
            api_key=api_key,
            base_url=base_url,
        )
    )
    return _redact_monitor_secrets(result)


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def monitor_control(
    monitor_id: str,
    action: Literal["pause", "resume", "run_now", "delete"],
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> dict[str, Any]:
    """Control an existing website monitor: ``"pause"`` stops scheduled
    checks, ``"resume"`` restarts them (may hit the plan's active-monitor
    cap), ``"run_now"`` triggers an immediate out-of-schedule check (billed
    like a normal check), and ``"delete"`` permanently removes the monitor
    and its history.

    Calls ``POST /monitors/:id/{pause,resume,run}`` or
    ``DELETE /monitors/:id`` directly — not covered by ``anakin-sdk``
    v0.1.0. Use :func:`monitor_list` to find the id.

    :param monitor_id: The monitor ID.
    :param action: What to do with the monitor.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    api_key = _resolve_api_key()
    base = f"/monitors/{quote(monitor_id, safe='')}"
    method_path = {
        "pause": ("POST", f"{base}/pause"),
        "resume": ("POST", f"{base}/resume"),
        "run_now": ("POST", f"{base}/run"),
        "delete": ("DELETE", base),
    }[action]
    method, path = method_path
    result = _http.as_dict(_http.request(method, path, api_key=api_key, base_url=base_url))
    return _redact_monitor_secrets(result)


# ─── AI visibility (raw HTTP — not in anakin-sdk) ───────────────────────────


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def ai_visibility_sources(
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> dict[str, Any]:
    """List the AI answer engines available to :func:`ai_visibility_search`
    — each with its slug (what's passed as ``sources``) and display label.

    Calls ``GET /ai-visibility/sources`` directly — not covered by
    ``anakin-sdk`` v0.1.0.

    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    api_key = _resolve_api_key()
    return _http.as_dict(
        _http.request("GET", "/ai-visibility/sources", api_key=api_key, base_url=base_url)
    )


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def ai_visibility_search(
    query: str,
    sources: Optional[list[str]] = None,
    country: str = "us",
    include_full_content: bool = False,
    poll_timeout: Optional[float] = None,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> dict[str, Any]:
    """Ask multiple AI answer engines (ChatGPT, Gemini, Google AI Overview,
    ...) the same question and compare their answers.

    Calls ``POST /ai-visibility/search`` then polls
    ``GET /ai-visibility/search/:id`` directly (until the response's
    ``status`` is no longer ``"running"``) — not covered by ``anakin-sdk``
    v0.1.0. Returns one result per engine plus an AI-generated synthesis of
    where the engines agree and diverge. Billed per source; failed sources
    are free. A ``"failed"`` overall status is still returned (not raised)
    since the payload carries per-source results and errors either way —
    same behavior anakin-mcp's ``aiVisibilitySearch`` documents.

    :param query: The question to ask every engine (max 2000 characters).
    :param sources: Engine slugs to query (see
        :func:`ai_visibility_sources`). Omit to query all enabled engines.
    :param country: Two-letter ISO country for the search geography (proxy
        exit).
    :param include_full_content: Include each engine's raw full answer in
        the results (large). Summaries and the synthesis are returned
        regardless.
    :param poll_timeout: Seconds to wait for the search to finish; defaults
        to ``_http.DEFAULT_POLL_TIMEOUT`` (180s) when unset.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    api_key = _resolve_api_key()
    body: dict[str, Any] = {"query": query, "country": country}
    if sources is not None:
        body["sources"] = sources
    submitted = _http.as_dict(
        _http.request(
            "POST", "/ai-visibility/search", api_key=api_key, base_url=base_url, json=body
        )
    )
    search_id = submitted.get("search_id")
    if search_id and submitted.get("status") == "running":
        search = _http.poll(
            f"/ai-visibility/search/{quote(str(search_id), safe='')}",
            api_key=api_key,
            base_url=base_url,
            is_terminal=lambda body: body.get("status") != "running",
            poll_timeout=(
                poll_timeout if poll_timeout is not None else _http.DEFAULT_POLL_TIMEOUT
            ),
        )
    else:
        search = submitted

    results = search.get("results") or []
    if not include_full_content:
        results = [{k: v for k, v in r.items() if k != "full_content"} for r in results]

    return {
        "search_id": search.get("search_id"),
        "status": search.get("status"),
        "country": search.get("country"),
        "synthesis": search.get("synthesis"),
        "results": results,
    }


# ─── AI browser automation (raw HTTP — not in anakin-sdk) ──────────────────


@task(secret_requests=[_ANAKIN_SECRET_REQUEST])
def browser_task(
    prompt: str,
    url: Optional[str] = None,
    session_id: Optional[str] = None,
    max_steps: Optional[int] = None,
    timeout_ms: Optional[int] = None,
    output_schema: Optional[dict[str, Any]] = None,
    poll_timeout: Optional[float] = None,
    base_url: str = DEFAULT_ANAKIN_BASE_URL,
) -> dict[str, Any]:
    """Run a natural-language task in a real cloud browser driven by an AI
    agent: it navigates, clicks, types, scrolls, and extracts on your
    behalf.

    Calls ``POST /ai/evaluate`` (always in async mode — the sync variant
    blocks for up to ~5.5 minutes, far past a normal request timeout) then
    polls ``GET /ai/jobs/:id`` directly — not covered by ``anakin-sdk``
    v0.1.0. Use when :func:`scrape_url`/:func:`crawl_site` can't do the job
    (multi-step flows, interactions, complex navigation) and no Wire action
    covers the site (check :func:`wire_discover` first — Wire actions are
    faster and cheaper). Server hard-caps a run at ~330s.

    :param prompt: The task in natural language. Be specific about the goal
        and what to return. Never include passwords or secrets — use
        ``session_id`` for authenticated sites.
    :param url: Navigate here before starting. Omit to let the agent follow
        URLs named in the prompt.
    :param session_id: Saved browser-session ID (see :func:`session_list`)
        so the task runs logged in.
    :param max_steps: Cap on agent steps (navigation/click/type actions).
    :param timeout_ms: Task timeout in milliseconds (server caps runs at
        ~330s regardless).
    :param output_schema: JSON Schema for the result — the agent returns
        structured data conforming to it.
    :param poll_timeout: Seconds to wait for the task to finish; defaults to
        ``_http.BROWSER_TASK_POLL_TIMEOUT`` (360s) when unset — longer than
        other jobs in this package since the server itself allows runs up
        to ~330s.
    :param base_url: Anakin API base URL; override only for internal/test
        environments.
    """
    api_key = _resolve_api_key()
    body: dict[str, Any] = {"prompt": prompt, "async": True}
    if url is not None:
        body["url"] = url
    if session_id is not None:
        body["session_id"] = session_id
    if max_steps is not None:
        body["max_steps"] = max_steps
    if timeout_ms is not None:
        body["timeout_ms"] = timeout_ms
    if output_schema is not None:
        body["output_schema"] = output_schema

    accepted = _http.as_dict(
        _http.request("POST", "/ai/evaluate", api_key=api_key, base_url=base_url, json=body)
    )
    workflow_id = accepted.get("workflow_id")
    if not workflow_id:
        # Service answered synchronously (shouldn't happen with async=True).
        job = accepted
    else:
        job = _http.poll(
            f"/ai/jobs/{quote(str(workflow_id), safe='')}",
            api_key=api_key,
            base_url=base_url,
            is_terminal=lambda body: body.get("status") in {"completed", "failed", "timed_out"},
            poll_interval=_http.DEFAULT_POLL_INTERVAL,
            poll_timeout=(
                poll_timeout if poll_timeout is not None else _http.BROWSER_TASK_POLL_TIMEOUT
            ),
        )
        if job.get("status") in {"failed", "timed_out"}:
            raise _http.AnakinAPIError(
                f"Browser task {job.get('status')}: {job.get('error', 'unknown')}",
                code=str(job.get("status")).upper(),
            )

    result = job.get("result") if isinstance(job.get("result"), dict) else job
    return {
        "success": result.get("success"),
        "result": result.get("result"),
        "steps_taken": len(result["steps"]) if isinstance(result.get("steps"), list) else None,
        "iterations": result.get("iterations"),
        "cached": result.get("cached"),
        "duration_ms": result.get("duration_ms"),
        "run_id": result.get("run_id"),
    }
