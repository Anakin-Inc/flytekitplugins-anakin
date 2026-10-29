"""Flyte tasks for the Anakin web data API (https://api.anakin.io/v1).

These are plain ``@task`` functions: Anakin is an HTTP API, so nothing here
needs a custom ``PythonTask`` type or a backend connector. Import them into a
workflow like any other task.

Every task except ``browser_task`` delegates to the official ``anakin-sdk``
client, which handles request bodies, retries on 429/5xx and job polling.
``browser_task`` calls ``POST /ai/evaluate`` directly because the SDK doesn't
wrap that endpoint yet.

Outputs are the SDK's Pydantic models (``Document``, ``WireResult``,
``Monitor``...), which flytekit serializes natively, so downstream tasks get
typed objects. Free-form JSON inputs and outputs (action params, JSON
Schemas, browser task results) are typed as plain ``dict``, which flytekit
stores as JSON; ``dict[str, Any]`` would make it pickle every value.

Auth: tasks read the API key from the Flyte secret ``anakin/api-key``
(``ANAKIN_SECRET_GROUP`` / ``ANAKIN_SECRET_KEY``), then the
``ANAKIN_API_KEY`` environment variable. With neither, the client runs in
keyless mode, where ``scrape_url``, ``wire_discover``, ``wire_catalogs`` and
``wire_catalog`` work on a small free per-IP allowance.

- Scrape and search: ``scrape_url``, ``map_site``, ``crawl_site``,
  ``search``, ``agentic_search``
- Wire: ``wire_discover``, ``wire_catalogs``, ``wire_catalog``,
  ``wire_read_action``, ``wire_write_action``, ``wire_identities``,
  ``wire_login``, ``wire_build``, ``wire_build_status``
- Website monitoring: ``monitor_create``, ``monitor_list``, ``monitor_get``,
  ``monitor_changes``, ``monitor_control``
- AI visibility: ``ai_visibility_sources``, ``ai_visibility_search``
- Browser: ``session_list``, ``session_delete``, ``browser_task``
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional, TypeVar

import httpx
from anakin import Anakin
from anakin.models import (
    AgenticSearchResult,
    AIVisibilitySearch,
    AIVisibilitySource,
    BrowserSession,
    CrawlResult,
    Document,
    MapResult,
    Monitor,
    MonitorChange,
    SearchResult,
    WireActionMatch,
    WireBuildRequest,
    WireCatalog,
    WireCatalogDetail,
    WireIdentity,
    WireLoginResult,
    WireResult,
)
from flytekit import Secret, current_context, task
from pydantic import BaseModel

from flytekitplugins.anakin import _http
from flytekitplugins.anakin._policy import financial_block_reason

#: Flyte secret holding the Anakin API key. Create it with
#: ``flytectl create secret --name api-key --group anakin --value ask_...``
#: (or your deployment's equivalent) before running on a cluster.
ANAKIN_SECRET_GROUP = "anakin"
ANAKIN_SECRET_KEY = "api-key"

#: Overridden by the ``ANAKIN_BASE_URL`` environment variable (internal and
#: test environments only).
DEFAULT_ANAKIN_BASE_URL = "https://api.anakin.io/v1"

_SECRET = Secret(group=ANAKIN_SECRET_GROUP, key=ANAKIN_SECRET_KEY)

logger = logging.getLogger("flytekitplugins.anakin")

_M = TypeVar("_M", bound=BaseModel)


def _api_key() -> Optional[str]:
    """The Flyte secret if one is mounted, else ``ANAKIN_API_KEY``, else None."""
    try:
        key = current_context().secrets.get(ANAKIN_SECRET_GROUP, ANAKIN_SECRET_KEY)
    except ValueError:
        # Raised when the secret is neither in the environment nor mounted,
        # e.g. under local `pyflyte run`.
        key = None
    return key or os.environ.get("ANAKIN_API_KEY") or None


def _base_url() -> str:
    return os.environ.get("ANAKIN_BASE_URL") or DEFAULT_ANAKIN_BASE_URL


def _client() -> Anakin:
    return Anakin(api_key=_api_key(), base_url=_base_url())


def _http_client() -> httpx.Client:
    key = _api_key()
    if not key:
        raise ValueError(
            "This task needs an Anakin API key: create the Flyte secret "
            f"{ANAKIN_SECRET_GROUP}/{ANAKIN_SECRET_KEY} or set ANAKIN_API_KEY. "
            "Get a key at https://anakin.io/dashboard (the free tier needs no card)."
        )
    return httpx.Client(base_url=_base_url(), headers={"X-API-Key": key}, timeout=60.0)


def _refuse_if_financial(text: str, what: str) -> None:
    blocked = financial_block_reason(text)
    if blocked:
        logger.error("Refusing %s: %s", what, blocked)
        raise ValueError(blocked)


def _redact(model: _M) -> _M:
    """Hide the webhook signing secret: Flyte stores task outputs and shows them in the UI."""
    if getattr(model, "alert_webhook_secret", None):
        return model.model_copy(update={"alert_webhook_secret": _http.REDACTED})
    return model


# ─── Scrape and search ──────────────────────────────────────────────────────


@task(secret_requests=[_SECRET])
def scrape_url(
    url: str,
    country: str = "us",
    use_browser: bool = False,
    generate_json: bool = False,
    output_schema: Optional[dict] = None,
    formats: Optional[list[str]] = None,
    force_fresh: bool = False,
    session_id: Optional[str] = None,
    session_name: Optional[str] = None,
    poll_timeout: Optional[float] = None,
) -> Document:
    """Scrape one URL to markdown, optionally extracting structured JSON with AI.

    Works without an API key on a small free per-IP allowance.

    :param url: The URL to scrape.
    :param country: Proxy country code, e.g. "us", "gb", "de".
    :param use_browser: Render with a headless browser. Use for JavaScript-heavy pages.
    :param generate_json: Extract structured JSON from the page with AI.
    :param output_schema: JSON Schema for the extracted JSON (implies AI extraction).
    :param formats: Output formats, any of "markdown" (default), "html",
        "cleaned_html", "screenshot", "links".
    :param force_fresh: Skip the cache and fetch the page again.
    :param session_id: Saved browser session to scrape as a logged-in user.
    :param session_name: Saved browser session name (alternative to ``session_id``).
    :param poll_timeout: Seconds to wait for the job (SDK default: 300).
    :return: The scraped ``Document``: ``markdown``, ``generated_json``, ``html`` and more.
    """
    logger.info("Scraping %s (use_browser=%s)", url, use_browser)
    document = _client().scrape(
        url,
        formats=tuple(formats or ("markdown",)),  # type: ignore[arg-type]
        country=country,
        use_browser=use_browser,
        generate_json=generate_json,
        output_schema=output_schema,
        force_fresh=force_fresh,
        session_id=session_id,
        session_name=session_name,
        poll_timeout=poll_timeout,
    )
    logger.info("Scraped %s (job %s, cached=%s)", url, document.id, document.cached)
    return document


@task(secret_requests=[_SECRET])
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
) -> MapResult:
    """Discover the URLs on a site (sitemap plus link traversal).

    Useful before ``crawl_site``, or to pick pages for ``scrape_url``.

    :param url: Starting URL, usually a homepage or section root.
    :param limit: Maximum URLs to return (max 5000).
    :param depth: Link hops to follow from ``url`` (max 5).
    :param limit_per_level: Maximum URLs collected per depth level.
    :param include_subdomains: Include URLs on subdomains of the starting host.
    :param include_external_links: Also collect (but don't follow) external links.
    :param search: Only return URLs whose path or title matches this keyword.
    :param use_browser: Render with a headless browser. Needed for SPAs.
    :param session_id: Saved browser session to map as a logged-in user.
    :param poll_timeout: Seconds to wait for the job (SDK default: 300).
    :return: ``links``, ``total_links``, ``external_links`` and timing.
    """
    logger.info("Mapping %s (depth=%d, limit=%d)", url, depth, limit)
    result = _client().map(
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
    logger.info("Map of %s found %d link(s)", url, result.total_links)
    return result


@task(secret_requests=[_SECRET])
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
) -> CrawlResult:
    """Fetch markdown for many pages of a site in one job.

    :param url: Starting URL.
    :param max_pages: Maximum pages fetched.
    :param depth: Link hops to follow from ``url``.
    :param include_patterns: Only fetch URLs matching at least one of these patterns.
    :param exclude_patterns: Skip URLs matching any of these patterns.
    :param country: Proxy country code.
    :param use_browser: Render each page with a headless browser.
    :param session_id: Saved browser session to crawl as a logged-in user.
    :param poll_timeout: Seconds to wait for the job (SDK default: 300).
    :return: ``total_pages``, ``completed_pages`` and ``pages`` (each with
        ``url``, ``status``, ``markdown`` and ``error``).
    """
    logger.info("Crawling %s (max_pages=%d, depth=%d)", url, max_pages, depth)
    result = _client().crawl(
        url,
        max_pages=max_pages,
        depth=depth,
        include_patterns=include_patterns or (),
        exclude_patterns=exclude_patterns or (),
        country=country,
        use_browser=use_browser,
        session_id=session_id,
        poll_timeout=poll_timeout,
    )
    logger.info(
        "Crawl of %s fetched %d/%d page(s)", url, result.completed_pages, result.total_pages
    )
    return result


@task(secret_requests=[_SECRET])
def search(prompt: str, limit: int = 5) -> SearchResult:
    """AI web search with citations. Synchronous.

    :param prompt: The search query or question.
    :param limit: Maximum results (max 20).
    :return: ``results``, each with ``url``, ``title``, ``snippet`` and ``date``.
    """
    logger.info("Searching: %s (limit=%d)", prompt, limit)
    result = _client().search(prompt, limit=limit)
    logger.info("Search returned %d result(s)", len(result.results))
    return result


@task(secret_requests=[_SECRET])
def agentic_search(
    prompt: str,
    use_browser: bool = True,
    schema: Optional[dict] = None,
    poll_timeout: Optional[float] = None,
) -> AgenticSearchResult:
    """Multi-step research: search, scrape the cited pages, return a structured answer.

    Takes minutes rather than seconds. Use ``search`` for quick lookups.

    :param prompt: The research question (max 8 KB).
    :param use_browser: Scrape citations with a headless browser.
    :param schema: Optional JSON Schema (max 50 KB) for ``structured_data``.
    :param poll_timeout: Seconds to wait for the job (SDK default: 300).
    :return: ``status`` and ``generated_json`` with ``summary``,
        ``structured_data`` and ``data_schema``.
    """
    logger.info("Running agentic search: %s", prompt)
    result = _client().agentic_search(
        prompt, use_browser=use_browser, schema=schema, poll_timeout=poll_timeout
    )
    logger.info("Agentic search %s finished with status=%s", result.id, result.status)
    return result


# ─── Wire ───────────────────────────────────────────────────────────────────


@task(secret_requests=[_SECRET])
def wire_discover(
    q: str, catalog: Optional[str] = None, limit: Optional[int] = None
) -> list[WireActionMatch]:
    """Find Wire actions for a task described in plain language.

    Works without an API key.

    :param q: What you want to do, e.g. "top phones on walmart".
    :param catalog: Restrict to one site's catalog slug, e.g. "amazon".
    :param limit: Maximum candidate actions to return.
    :return: Ranked actions, each with ``action_id``, ``catalog_slug``,
        ``params`` and ``credits``. Pass an ``action_id`` to
        ``wire_read_action`` or ``wire_write_action``.
    """
    logger.info("Discovering Wire actions for: %s", q)
    matches = _client().wire.discover(q, catalog=catalog, limit=limit)
    logger.info("Wire discovery returned %d action(s)", len(matches))
    return matches


@task(secret_requests=[_SECRET])
def wire_catalogs() -> list[WireCatalog]:
    """List every site in the Wire catalog with its action count.

    Works without an API key.

    :return: One entry per site; pass its ``slug`` to ``wire_catalog``.
    """
    return _client().wire.catalogs()


@task(secret_requests=[_SECRET])
def wire_catalog(slug: str) -> WireCatalogDetail:
    """One Wire site's actions: parameter schema, mode, auth mode, credit cost.

    Works without an API key.

    :param slug: The site, e.g. "walmart" (see ``wire_catalogs``).
    :return: The site's actions and, if it needs credentials, its login fields.
    """
    logger.info("Fetching Wire catalog %s", slug)
    return _client().wire.catalog(slug)


@task(secret_requests=[_SECRET])
def wire_read_action(
    action_id: str,
    params: Optional[dict] = None,
    credential_id: Optional[str] = None,
    identity_id: Optional[str] = None,
    poll_timeout: Optional[float] = None,
) -> WireResult:
    """Run a Wire read action, which extracts data without changing anything on the site.

    For actions that change state, use ``wire_write_action``.

    :param action_id: The action to run, from ``wire_discover`` or ``wire_catalog``.
    :param params: The action's parameters, as described by discovery.
    :param credential_id: Needed when the action's ``auth_mode`` is "required".
        Get one from ``wire_identities`` or ``wire_login``.
    :param identity_id: Alternative to ``credential_id``: run as this saved identity.
    :param poll_timeout: Seconds to wait for the job (SDK default: 300).
    :return: ``job_id``, ``status``, ``data``, ``credits_used`` and ``error``.
    """
    logger.info("Running Wire read action %s", action_id)
    result = _client().wire.run(
        action_id,
        params or {},
        credential_id=credential_id,
        identity_id=identity_id,
        poll_timeout=poll_timeout,
    )
    logger.info("Wire action %s finished with status=%s", action_id, result.status)
    return result


@task(secret_requests=[_SECRET])
def wire_write_action(
    action_id: str,
    params: Optional[dict] = None,
    credential_id: Optional[str] = None,
    identity_id: Optional[str] = None,
    poll_timeout: Optional[float] = None,
) -> WireResult:
    """Run a Wire write action: submit a form, add to cart, post content, update settings.

    Don't give this task Flyte ``retries`` or ``cache``: repeating a write
    can duplicate it. Refuses (raises ``ValueError`` before calling the API)
    anything that looks like a payment or fund transfer.

    :param action_id: The action to run, from ``wire_discover`` or ``wire_catalog``.
    :param params: The action's parameters, as described by discovery.
    :param credential_id: Needed when the action's ``auth_mode`` is "required".
    :param identity_id: Alternative to ``credential_id``: run as this saved identity.
    :param poll_timeout: Seconds to wait for the job (SDK default: 300).
    :return: Same shape as ``wire_read_action``.
    """
    resolved_params = params or {}
    _refuse_if_financial(f"{action_id} {resolved_params}", f"Wire action {action_id}")

    logger.info("Running Wire write action %s", action_id)
    result = _client().wire.run(
        action_id,
        resolved_params,
        credential_id=credential_id,
        identity_id=identity_id,
        poll_timeout=poll_timeout,
    )
    logger.info("Wire action %s finished with status=%s", action_id, result.status)
    return result


@task(secret_requests=[_SECRET])
def wire_identities(catalog_id: Optional[str] = None) -> list[WireIdentity]:
    """List your saved Wire identities (site accounts) and their credentials.

    :param catalog_id: Only identities for this catalog.
    :return: Identities, each with ``credentials``; every credential's ``id``
        can be passed as ``credential_id`` to the Wire action tasks.
    """
    return _client().wire.identities(catalog_id=catalog_id)


@task(secret_requests=[_SECRET])
def wire_login(
    catalog_slug: str,
    params: Optional[dict] = None,
    identity_name: Optional[str] = None,
    source_id: Optional[str] = None,
    source_ref: Optional[dict] = None,
) -> WireLoginResult:
    """Sign in to a site that needs credentials and get a ``credential_id``.

    Anakin stores the encrypted session, never the password. Flyte records
    task inputs, so don't pass a password literal from workflow code: read it
    from a Flyte secret inside a task, or use a 1Password ``source_id``.

    :param catalog_slug: The site to sign in to.
    :param params: The login fields listed in ``wire_catalog(slug)``'s
        ``login_input_schema``, e.g. ``{"email": ..., "password": ...}``.
    :param identity_name: Name for the identity.
    :param source_id: 1Password identity source, instead of ``params``.
    :param source_ref: 1Password item locator (``vault_id``, ``item_id``,
        ``fields``), used with ``source_id``.
    :return: The login result, including the new ``credential_id``.
    """
    logger.info("Signing in to Wire catalog %s", catalog_slug)  # never log params
    return _client().wire.login(
        catalog_slug,
        params,
        identity_name=identity_name,
        source_id=source_id,
        source_ref=source_ref,
    )


@task(secret_requests=[_SECRET])
def wire_build(
    website_url: str,
    goal: str,
    catalog_id: Optional[str] = None,
    visibility: str = "private",
    force: bool = False,
) -> WireBuildRequest:
    """Ask Anakin to build a new Wire action for a site that isn't in the catalog.

    Builds run asynchronously: this returns the pending build request. Check
    on it with ``wire_build_status``. Charges credits up front, refunded if
    the build fails. Run ``wire_discover`` first to make sure no action
    exists. Refuses payment or fund-transfer goals (raises ``ValueError``).

    :param website_url: The site to build an action for.
    :param goal: What the action should do or extract. Be specific.
    :param catalog_id: Attach to an existing catalog instead of creating one.
    :param visibility: "private" (default) or "public".
    :param force: Build even if similar actions already exist for the domain.
    :return: The build request: ``id``, ``status`` and related fields.
    """
    _refuse_if_financial(f"{goal} {website_url}", f"Wire build for {website_url}")

    logger.info("Requesting a Wire action for %s: %s", website_url, goal)
    build = _client().wire.build(
        website_url, goal, catalog_id=catalog_id, visibility=visibility, force=force
    )
    logger.info("Wire build %s is %s", build.id, build.status)
    return build


@task(secret_requests=[_SECRET])
def wire_build_status(build_id: str) -> WireBuildRequest:
    """Check a Wire build request started with ``wire_build``.

    :param build_id: The ``id`` returned by ``wire_build``.
    :return: The build's ``status`` and, once published, its ``action_id``.
    """
    return _client().wire.get_build(build_id)


# ─── Website monitoring ─────────────────────────────────────────────────────


_MONITOR_ACTIONS = ("pause", "resume", "run_now", "delete")


@task(secret_requests=[_SECRET])
def monitor_create(
    url: str,
    interval_minutes: int,
    scope: str = "page",
    watch_mode: str = "full_page",
    watch_format: str = "markdown",
    output_schema: Optional[dict] = None,
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
    wire_params: Optional[dict] = None,
    wire_watch_paths: Optional[list[str]] = None,
) -> Monitor:
    """Create a scheduled website monitor.

    Checks ``url`` every ``interval_minutes`` (minimum 15) and records a
    change when the content differs, optionally alerting a webhook or email.
    ``scope="page"`` watches one URL, ``"site"`` crawls the site and tracks
    pages added, removed and changed, and ``"wire"`` runs a Wire action each
    check and diffs its JSON. ``watch_mode="specific_data"`` tracks only the
    fields in ``output_schema`` (prices, stock, status). ``ai_mode`` filters
    out trivial changes and summarizes real ones. See
    https://anakin.io/pricing for the credit cost per check and the
    active-monitor limit on each plan.

    Creating a monitor isn't idempotent: don't give this task ``retries``.

    :param url: The URL to watch (the root URL for site scope).
    :param interval_minutes: Minutes between checks. Minimum 15.
    :param scope: "page", "site" or "wire".
    :param watch_mode: "full_page" or "specific_data".
    :param watch_format: Compared format in full_page mode: "markdown",
        "html" or "cleaned_html".
    :param output_schema: JSON Schema of the fields to track. Required for
        ``watch_mode="specific_data"``.
    :param ai_mode: Filter out trivial changes with AI.
    :param ai_goal: Which changes count as meaningful (used with ``ai_mode``).
    :param use_browser: Check with a headless browser.
    :param country: Proxy country code.
    :param session_id: Saved browser session for login-protected pages.
    :param is_active: Start checking immediately.
    :param expires_at: End date (ISO 8601 or ``YYYY-MM-DD``); the monitor pauses then.
    :param alert_webhook_url: Webhook that receives signed change alerts.
    :param alert_emails: Comma-separated email recipients for change alerts.
    :param max_pages: Site scope: maximum pages per run.
    :param max_depth: Site scope: crawl depth (1-5).
    :param include_patterns: Site scope: patterns or URLs to track.
    :param exclude_patterns: Site scope: patterns to skip.
    :param wire_action_id: Wire scope (required there): the action to run each check.
    :param wire_catalog_slug: Wire scope: the action's catalog slug.
    :param wire_credential_id: Wire scope: credential for actions that need auth.
    :param wire_params: Wire scope: parameters for the action.
    :param wire_watch_paths: Wire scope: JSON paths to diff instead of the whole result.
    :return: The new monitor. The webhook signing secret is redacted; read it
        in the Anakin dashboard.
    """
    logger.info("Creating monitor for %s (scope=%s, every %dm)", url, scope, interval_minutes)
    options: dict[str, Any] = {
        "scope": scope,
        "watch_mode": watch_mode,
        "watch_format": watch_format,
        "ai_mode": ai_mode,
        "use_browser": use_browser,
        "country": country,
        "is_active": is_active,
    }
    optional: dict[str, Any] = {
        "output_schema": output_schema,
        "ai_goal": ai_goal,
        "session_id": session_id,
        "expires_at": expires_at,
        "alert_webhook_url": alert_webhook_url,
        "alert_emails": alert_emails,
        "max_pages": max_pages,
        "max_depth": max_depth,
        "include_patterns": include_patterns,
        "exclude_patterns": exclude_patterns,
        "wire_action_id": wire_action_id,
        "wire_catalog_slug": wire_catalog_slug,
        "wire_credential_id": wire_credential_id,
        "wire_params": wire_params,
        "wire_watch_paths": wire_watch_paths,
    }
    options.update({k: v for k, v in optional.items() if v is not None})

    monitor = _client().monitors.create(url, interval_minutes, **options)
    logger.info("Created monitor %s for %s", monitor.id, url)
    return _redact(monitor)


@task(secret_requests=[_SECRET])
def monitor_list() -> list[Monitor]:
    """List your website monitors.

    :return: Every monitor, with webhook signing secrets redacted.
    """
    return [_redact(m) for m in _client().monitors.list()]


@task(secret_requests=[_SECRET])
def monitor_get(monitor_id: str) -> Monitor:
    """Fetch one monitor's configuration and status.

    :param monitor_id: The monitor's ``id``.
    :return: The monitor, with its webhook signing secret redacted.
    """
    return _redact(_client().monitors.get(monitor_id))


@task(secret_requests=[_SECRET])
def monitor_changes(monitor_id: str) -> list[MonitorChange]:
    """Get the changes a monitor has detected, newest first.

    :param monitor_id: The monitor's ``id``.
    :return: One entry per detected change, with its diff and (when
        ``ai_mode`` is on) the AI summary.
    """
    logger.info("Fetching changes for monitor %s", monitor_id)
    return _client().monitors.changes(monitor_id)


@task(secret_requests=[_SECRET])
def monitor_control(monitor_id: str, action: str) -> Optional[dict]:
    """Pause, resume, run, or delete a monitor.

    :param monitor_id: The monitor's ``id``.
    :param action: "pause", "resume", "run_now" (an immediate check, billed
        like a scheduled one) or "delete" (removes the monitor and its history).
    :return: The updated monitor for pause/resume, the queued run
        (``success``, ``job_id``, ``message``) for run_now, and None for delete.
    """
    if action not in _MONITOR_ACTIONS:
        raise ValueError(
            f"Unknown monitor action {action!r}: use one of {', '.join(_MONITOR_ACTIONS)}."
        )

    logger.info("Monitor %s: %s", monitor_id, action)
    monitors = _client().monitors
    if action == "delete":
        monitors.delete(monitor_id)
        return None
    if action == "pause":
        result: BaseModel = monitors.pause(monitor_id)
    elif action == "resume":
        result = monitors.resume(monitor_id)
    else:
        result = monitors.run_now(monitor_id)
    return _redact(result).model_dump(mode="json")


# ─── AI visibility ──────────────────────────────────────────────────────────


@task(secret_requests=[_SECRET])
def ai_visibility_sources() -> list[AIVisibilitySource]:
    """List the AI answer engines ``ai_visibility_search`` can query.

    :return: Each engine's slug (pass these as ``sources``) and display name.
    """
    return _client().ai_visibility.sources()


@task(secret_requests=[_SECRET])
def ai_visibility_search(
    query: str,
    sources: Optional[list[str]] = None,
    country: str = "us",
    include_full_content: bool = False,
    poll_timeout: Optional[float] = None,
) -> AIVisibilitySearch:
    """Ask several AI answer engines (ChatGPT, Gemini, Google AI Overview, ...) one question.

    Useful for checking how a brand or topic shows up in AI answers, per
    country. Billed per engine that answers; failed engines are free. A
    search where some engines failed is returned, not raised.

    :param query: The question (max 2000 characters).
    :param sources: Engine slugs from ``ai_visibility_sources``. Omit for all.
    :param country: Two-letter country code for the search location.
    :param include_full_content: Keep each engine's full answer text. Off by
        default; summaries and the cross-engine synthesis are always returned.
    :param poll_timeout: Seconds to wait for the search (SDK default: 300).
    :return: ``search_id``, ``status``, ``synthesis`` and one ``results``
        entry per engine.
    """
    logger.info("Running AI visibility search: %s", query)
    result = _client().ai_visibility.search(
        query, sources=sources, country=country, poll_timeout=poll_timeout
    )
    if not include_full_content:
        result = result.model_copy(
            update={
                "results": [r.model_copy(update={"full_content": None}) for r in result.results]
            }
        )
    logger.info("AI visibility search %s: %s", result.search_id, result.status)
    return result


# ─── Browser sessions and AI browser tasks ──────────────────────────────────


@task(secret_requests=[_SECRET])
def session_list(domain: Optional[str] = None) -> list[BrowserSession]:
    """List saved browser sessions (logged-in states you created in the Anakin dashboard).

    Pass a session's ``id`` as ``session_id`` to ``scrape_url``,
    ``crawl_site``, ``monitor_create`` or ``browser_task`` to run as that
    logged-in user.

    :param domain: Only sessions for this domain, e.g. "amazon.com".
    :return: Sessions with ``id``, ``name``, ``website_domain`` and ``is_active``.
    """
    return _client().sessions.list(domain=domain)


@task(secret_requests=[_SECRET])
def session_delete(session_id: str) -> None:
    """Permanently delete a saved browser session and its encrypted login data.

    Anything that uses this session loses its logged-in access.

    :param session_id: The session's ``id``, from ``session_list``.
    """
    logger.info("Deleting browser session %s", session_id)
    _client().sessions.delete(session_id)


@task(secret_requests=[_SECRET])
def browser_task(
    prompt: str,
    url: Optional[str] = None,
    session_id: Optional[str] = None,
    max_steps: Optional[int] = None,
    timeout_ms: Optional[int] = None,
    output_schema: Optional[dict] = None,
) -> dict:
    """Run a task described in plain language in a cloud browser driven by an AI agent.

    The agent navigates, clicks, types and extracts. Use it for multi-step
    flows ``scrape_url`` can't do and no Wire action covers (Wire actions are
    faster and cheaper, so try ``wire_discover`` first). Runs are capped at
    about 330 seconds server-side. For logged-in tasks pass ``session_id``;
    never put passwords in ``prompt``. Refuses payment or fund-transfer tasks
    (raises ``ValueError``).

    :param prompt: What to do and what to return.
    :param url: Start here. Omit to let the agent follow URLs in the prompt.
    :param session_id: Saved browser session to run as a logged-in user.
    :param max_steps: Maximum agent steps.
    :param timeout_ms: Task timeout in milliseconds.
    :param output_schema: JSON Schema the returned ``result`` should follow.
    :return: ``success``, ``result``, ``steps_taken``, ``iterations``,
        ``cached``, ``duration_ms`` and ``run_id``.
    :raises RuntimeError: If the task fails or times out.
    """
    _refuse_if_financial(f"{prompt} {url or ''}", "browser task")

    logger.info("Running browser task: %s", prompt)
    body: dict[str, Any] = {"prompt": prompt, "async": True}
    optional = {
        "url": url,
        "session_id": session_id,
        "max_steps": max_steps,
        "timeout_ms": timeout_ms,
        "output_schema": output_schema,
    }
    body.update({k: v for k, v in optional.items() if v is not None})

    with _http_client() as http_client:
        accepted = _http.request(http_client, "POST", "/ai/evaluate", json=body)
        workflow_id = accepted.get("workflow_id")
        if not workflow_id:
            resolved = accepted
        else:
            job = _http.poll(
                http_client,
                f"/ai/jobs/{workflow_id}",
                is_terminal=lambda b: b.get("status") in {"completed", "failed", "timed_out"},
            )
            if job.get("status") in {"failed", "timed_out"}:
                raise RuntimeError(
                    f"Browser task {job.get('status')}: {job.get('error', 'unknown')}"
                )
            resolved = job.get("result") or job

    logger.info("Browser task finished (run_id=%s)", resolved.get("run_id"))
    steps = resolved.get("steps")
    return {
        "success": resolved.get("success"),
        "result": resolved.get("result"),
        "steps_taken": len(steps) if isinstance(steps, list) else None,
        "iterations": resolved.get("iterations"),
        "cached": resolved.get("cached"),
        "duration_ms": resolved.get("duration_ms"),
        "run_id": resolved.get("run_id"),
    }
