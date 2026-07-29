"""Unit tests for the Anakin flytekit tasks.

Two mocking strategies, matching the two implementation strategies in
`tasks.py`:

- SDK-backed tasks (`scrape_url`, `search`, `agentic_search`, `map_site`,
  `crawl_site`, `wire_read_action`, `wire_write_action`, `session_list`,
  `session_delete`) mock `flytekitplugins.anakin.tasks.Anakin` (the SDK
  client class) entirely — these test the task <-> anakin-sdk wiring
  (kwargs passed through, the SDK's return value returned as-is), not the
  SDK or Flyte's runtime themselves.
- Raw-HTTP tasks (the 12 endpoints anakin-sdk v0.1.0 doesn't implement) mock
  `flytekitplugins.anakin.tasks._http.request`/`.poll` — these test the
  task <-> REST wiring (method/path/body built correctly, response shaped
  correctly), not `httpx` or the live API itself.

Tasks are called directly, which is flytekit's own supported pattern for
exercising `@task` functions without a running Flyte backend ("local
execution" — see flytekit's testing docs). Requires `flytekit` and
`anakin-sdk` installed to *run*; see SUBMIT.md for why that wasn't exercised
in this environment.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from anakin.models import (
    AgenticSearchResult,
    BrowserSession,
    CrawlResult,
    Document,
    MapResult,
    SearchResult,
    WireResult,
)

from flytekitplugins.anakin.tasks import (
    ANAKIN_SECRET_GROUP,
    ANAKIN_SECRET_KEY,
    DEFAULT_ANAKIN_BASE_URL,
    agentic_search,
    ai_visibility_search,
    ai_visibility_sources,
    browser_task,
    crawl_site,
    map_site,
    monitor_changes,
    monitor_control,
    monitor_create,
    monitor_list,
    scrape_url,
    search,
    session_delete,
    session_list,
    wire_build,
    wire_catalog,
    wire_discover,
    wire_identities,
    wire_login,
    wire_read_action,
    wire_write_action,
)


def test_secret_group_and_key_and_base_url_defaults() -> None:
    assert ANAKIN_SECRET_GROUP == "anakin"
    assert ANAKIN_SECRET_KEY == "api-key"
    assert DEFAULT_ANAKIN_BASE_URL == "https://api.anakin.io/v1"


def test_scrape_url_task_returns_document() -> None:
    document = Document(
        id="job_1",
        url="https://example.com",
        status="completed",
        cached=False,
        duration_ms=120,
        markdown="# Hello",
    )
    with patch("flytekitplugins.anakin.tasks.Anakin") as mock_anakin_cls:
        mock_anakin_cls.return_value.scrape.return_value = document
        result = scrape_url(url="https://example.com")

    assert result.markdown == "# Hello"
    assert result.id == "job_1"
    mock_anakin_cls.return_value.scrape.assert_called_once_with(
        "https://example.com",
        country="us",
        use_browser=False,
        generate_json=False,
        force_fresh=False,
        session_id=None,
        session_name=None,
        poll_timeout=None,
    )


def test_search_task_returns_search_result() -> None:
    search_result = SearchResult(id="job_2", results=[])
    with patch("flytekitplugins.anakin.tasks.Anakin") as mock_anakin_cls:
        mock_anakin_cls.return_value.search.return_value = search_result
        result = search(prompt="latest AI agents", limit=3)

    assert result.id == "job_2"
    assert result.results == []
    mock_anakin_cls.return_value.search.assert_called_once_with(
        "latest AI agents", limit=3
    )


def test_agentic_search_task_returns_agentic_search_result() -> None:
    agentic_result = AgenticSearchResult(id="job_3", status="completed")
    with patch("flytekitplugins.anakin.tasks.Anakin") as mock_anakin_cls:
        mock_anakin_cls.return_value.agentic_search.return_value = agentic_result
        result = agentic_search(prompt="compare CRMs")

    assert result.id == "job_3"
    assert result.status == "completed"
    mock_anakin_cls.return_value.agentic_search.assert_called_once_with(
        "compare CRMs", use_browser=True, schema=None, poll_timeout=None
    )


def test_agentic_search_default_use_browser_is_true() -> None:
    """agentic_search defaults use_browser=True (opposite of scrape_url's
    False default) — per anakin-py/src/anakin/client.py, preserved here
    rather than flattened to one default across both tasks."""
    agentic_result = AgenticSearchResult(id="job_4", status="completed")
    with patch("flytekitplugins.anakin.tasks.Anakin") as mock_anakin_cls:
        mock_anakin_cls.return_value.agentic_search.return_value = agentic_result
        agentic_search(prompt="compare CRMs")

    _, kwargs = mock_anakin_cls.return_value.agentic_search.call_args
    assert kwargs["use_browser"] is True


# ─── SDK-backed: map_site, crawl_site, wire_read_action, wire_write_action,
# session_list, session_delete ───────────────────────────────────────────────


def test_map_site_task_returns_map_result() -> None:
    map_result = MapResult(id="job_5", url="https://example.com", links=["https://example.com/a"])
    with patch("flytekitplugins.anakin.tasks.Anakin") as mock_anakin_cls:
        mock_anakin_cls.return_value.map.return_value = map_result
        result = map_site(url="https://example.com", depth=3)

    assert result.id == "job_5"
    assert result.links == ["https://example.com/a"]
    mock_anakin_cls.return_value.map.assert_called_once_with(
        "https://example.com",
        limit=100,
        depth=3,
        limit_per_level=100,
        include_subdomains=False,
        include_external_links=False,
        search=None,
        use_browser=False,
        session_id=None,
        poll_timeout=None,
    )


def test_crawl_site_task_returns_crawl_result() -> None:
    crawl_result = CrawlResult(id="job_6", url="https://example.com", total_pages=2)
    with patch("flytekitplugins.anakin.tasks.Anakin") as mock_anakin_cls:
        mock_anakin_cls.return_value.crawl.return_value = crawl_result
        result = crawl_site(url="https://example.com", max_pages=5)

    assert result.id == "job_6"
    assert result.total_pages == 2
    mock_anakin_cls.return_value.crawl.assert_called_once_with(
        "https://example.com",
        max_pages=5,
        depth=1,
        include_patterns=(),
        exclude_patterns=(),
        country="us",
        use_browser=False,
        session_id=None,
        poll_timeout=None,
    )


def test_wire_read_action_task_returns_wire_result() -> None:
    wire_result = WireResult(job_id="job_7", status="completed", data={"price": 10})
    with patch("flytekitplugins.anakin.tasks.Anakin") as mock_anakin_cls:
        mock_anakin_cls.return_value.wire.return_value = wire_result
        result = wire_read_action(action_id="walmart.get_product", params={"url": "https://x"})

    assert result.job_id == "job_7"
    assert result.data == {"price": 10}
    mock_anakin_cls.return_value.wire.assert_called_once_with(
        "walmart.get_product", {"url": "https://x"}, poll_timeout=None
    )


def test_wire_write_action_task_returns_wire_result() -> None:
    wire_result = WireResult(job_id="job_8", status="completed")
    with patch("flytekitplugins.anakin.tasks.Anakin") as mock_anakin_cls:
        mock_anakin_cls.return_value.wire.return_value = wire_result
        result = wire_write_action(action_id="neb.submit_form")

    assert result.job_id == "job_8"
    mock_anakin_cls.return_value.wire.assert_called_once_with(
        "neb.submit_form", {}, poll_timeout=None
    )


def test_session_list_task_returns_sessions() -> None:
    session = BrowserSession(sessionId="sess_1", name="my session", isActive=True)
    with patch("flytekitplugins.anakin.tasks.Anakin") as mock_anakin_cls:
        mock_anakin_cls.return_value.sessions.list.return_value = [session]
        result = session_list(domain="amazon.com")

    assert result == [session]
    mock_anakin_cls.return_value.sessions.list.assert_called_once_with(domain="amazon.com")


def test_session_delete_task_calls_sdk_delete() -> None:
    with patch("flytekitplugins.anakin.tasks.Anakin") as mock_anakin_cls:
        session_delete(session_id="sess_1")

    mock_anakin_cls.return_value.sessions.delete.assert_called_once_with("sess_1")


# ─── Raw HTTP: wire discovery/catalog/identities/login/build ───────────────


def test_wire_discover_task_calls_wire_resolve() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request:
        mock_request.return_value = {"results": [{"action_id": "walmart.search"}]}
        result = wire_discover(q="top phones on walmart", limit=3)

    assert result == {"results": [{"action_id": "walmart.search"}]}
    mock_request.assert_called_once_with(
        "GET",
        "/wire/resolve",
        api_key="ak-test",
        base_url=DEFAULT_ANAKIN_BASE_URL,
        params={"q": "top phones on walmart", "limit": 3},
    )


def test_wire_catalog_task_with_slug() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request:
        mock_request.return_value = {"slug": "walmart", "actions": []}
        result = wire_catalog(slug="walmart")

    assert result == {"slug": "walmart", "actions": []}
    mock_request.assert_called_once_with(
        "GET", "/wire/catalog/walmart", api_key="ak-test", base_url=DEFAULT_ANAKIN_BASE_URL
    )


def test_wire_catalog_task_without_slug_lists_all() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request:
        mock_request.return_value = {"catalogs": []}
        wire_catalog()

    mock_request.assert_called_once_with(
        "GET", "/wire/catalog", api_key="ak-test", base_url=DEFAULT_ANAKIN_BASE_URL
    )


def test_wire_identities_task() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request:
        mock_request.return_value = {"identities": []}
        result = wire_identities(catalog_id="walmart")

    assert result == {"identities": []}
    mock_request.assert_called_once_with(
        "GET",
        "/wire/identities",
        api_key="ak-test",
        base_url=DEFAULT_ANAKIN_BASE_URL,
        params={"catalog_id": "walmart"},
    )


def test_wire_login_task_builds_body() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request:
        mock_request.return_value = {"credential_id": "cred_1"}
        result = wire_login(
            catalog_slug="neb", params={"email": "a@b.com", "password": "secret"}
        )

    assert result == {"credential_id": "cred_1"}
    mock_request.assert_called_once_with(
        "POST",
        "/wire/login",
        api_key="ak-test",
        base_url=DEFAULT_ANAKIN_BASE_URL,
        json={
            "catalog_slug": "neb",
            "params": {"email": "a@b.com", "password": "secret"},
        },
    )


def test_wire_build_task_builds_body() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request:
        mock_request.return_value = {"status": "pending"}
        result = wire_build(website_url="https://newsite.com", goal="extract prices")

    assert result == {"status": "pending"}
    mock_request.assert_called_once_with(
        "POST",
        "/wire/build-request",
        api_key="ak-test",
        base_url=DEFAULT_ANAKIN_BASE_URL,
        json={
            "website_url": "https://newsite.com",
            "goal": "extract prices",
            "visibility": "private",
            "force": False,
        },
    )


# ─── Raw HTTP: monitors ─────────────────────────────────────────────────────


def test_monitor_create_task_redacts_webhook_secret() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request:
        mock_request.return_value = {
            "id": "mon_1",
            "url": "https://example.com",
            "alertWebhookSecret": "whsec_super_secret",
        }
        result = monitor_create(url="https://example.com", interval_minutes=30)

    assert result["id"] == "mon_1"
    assert result["alertWebhookSecret"] == "[redacted — view in the Anakin dashboard]"
    _, kwargs = mock_request.call_args
    assert kwargs["json"] == {
        "url": "https://example.com",
        "intervalMinutes": 30,
        "scope": "page",
        "watchMode": "full_page",
        "watchFormat": "markdown",
        "aiMode": False,
        "useBrowser": False,
        "country": "us",
        "isActive": True,
    }


def test_monitor_list_task_with_id_fetches_single_monitor() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request:
        mock_request.return_value = {"id": "mon_1"}
        result = monitor_list(monitor_id="mon_1")

    assert result == {"id": "mon_1"}
    mock_request.assert_called_once_with(
        "GET", "/monitors/mon_1", api_key="ak-test", base_url=DEFAULT_ANAKIN_BASE_URL
    )


def test_monitor_changes_task() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request:
        mock_request.return_value = {"changes": []}
        result = monitor_changes(monitor_id="mon_1")

    assert result == {"changes": []}
    mock_request.assert_called_once_with(
        "GET", "/monitors/mon_1/changes", api_key="ak-test", base_url=DEFAULT_ANAKIN_BASE_URL
    )


def test_monitor_control_run_now_maps_to_run_path() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request:
        mock_request.return_value = {"id": "mon_1", "status": "running"}
        monitor_control(monitor_id="mon_1", action="run_now")

    mock_request.assert_called_once_with(
        "POST", "/monitors/mon_1/run", api_key="ak-test", base_url=DEFAULT_ANAKIN_BASE_URL
    )


def test_monitor_control_delete_uses_delete_verb() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request:
        mock_request.return_value = {}
        monitor_control(monitor_id="mon_1", action="delete")

    mock_request.assert_called_once_with(
        "DELETE", "/monitors/mon_1", api_key="ak-test", base_url=DEFAULT_ANAKIN_BASE_URL
    )


# ─── Raw HTTP: AI visibility ────────────────────────────────────────────────


def test_ai_visibility_sources_task() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request:
        mock_request.return_value = {"sources": [{"slug": "chatgpt"}]}
        result = ai_visibility_sources()

    assert result == {"sources": [{"slug": "chatgpt"}]}
    mock_request.assert_called_once_with(
        "GET", "/ai-visibility/sources", api_key="ak-test", base_url=DEFAULT_ANAKIN_BASE_URL
    )


def test_ai_visibility_search_task_strips_full_content_by_default() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request:
        mock_request.return_value = {
            "search_id": "srch_1",
            "status": "completed",
            "country": "us",
            "synthesis": "Both engines agree.",
            "results": [{"source": "chatgpt", "summary": "...", "full_content": "huge text"}],
        }
        result = ai_visibility_search(query="what is Anakin?")

    assert result["search_id"] == "srch_1"
    assert result["results"] == [{"source": "chatgpt", "summary": "..."}]
    mock_request.assert_called_once_with(
        "POST",
        "/ai-visibility/search",
        api_key="ak-test",
        base_url=DEFAULT_ANAKIN_BASE_URL,
        json={"query": "what is Anakin?", "country": "us"},
    )


def test_ai_visibility_search_task_polls_when_still_running() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request, patch("flytekitplugins.anakin.tasks._http.poll") as mock_poll:
        mock_request.return_value = {"search_id": "srch_2", "status": "running"}
        mock_poll.return_value = {
            "search_id": "srch_2",
            "status": "completed",
            "results": [],
        }
        result = ai_visibility_search(query="what is Anakin?", include_full_content=True)

    assert result["status"] == "completed"
    mock_poll.assert_called_once()
    args, kwargs = mock_poll.call_args
    assert args[0] == "/ai-visibility/search/srch_2"
    assert kwargs["poll_timeout"] == 180.0  # _http.DEFAULT_POLL_TIMEOUT


# ─── Raw HTTP: browser_task ─────────────────────────────────────────────────


def test_browser_task_polls_workflow_and_shapes_result() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request, patch("flytekitplugins.anakin.tasks._http.poll") as mock_poll:
        mock_request.return_value = {"workflow_id": "wf_1", "status": "running"}
        mock_poll.return_value = {
            "status": "completed",
            "result": {
                "success": True,
                "result": {"price": "$499"},
                "steps": [1, 2, 3],
                "iterations": 3,
                "cached": False,
                "duration_ms": 4200,
                "run_id": "run_1",
            },
        }
        result = browser_task(prompt="find the price", url="https://example.com")

    assert result["success"] is True
    assert result["steps_taken"] == 3
    assert result["run_id"] == "run_1"
    mock_request.assert_called_once_with(
        "POST",
        "/ai/evaluate",
        api_key="ak-test",
        base_url=DEFAULT_ANAKIN_BASE_URL,
        json={"prompt": "find the price", "async": True, "url": "https://example.com"},
    )
    mock_poll.assert_called_once()
    args, kwargs = mock_poll.call_args
    assert args[0] == "/ai/jobs/wf_1"
    assert kwargs["poll_timeout"] == 360.0  # _http.BROWSER_TASK_POLL_TIMEOUT


def test_browser_task_raises_on_failed_status() -> None:
    with patch("flytekitplugins.anakin.tasks._resolve_api_key", return_value="ak-test"), patch(
        "flytekitplugins.anakin.tasks._http.request"
    ) as mock_request, patch("flytekitplugins.anakin.tasks._http.poll") as mock_poll:
        mock_request.return_value = {"workflow_id": "wf_2", "status": "running"}
        mock_poll.return_value = {"status": "failed", "error": "site blocked the agent"}

        try:
            browser_task(prompt="do the impossible")
        except Exception as exc:  # noqa: BLE001 — asserting the raised type below
            assert "Browser task failed" in str(exc)
        else:
            raise AssertionError("expected browser_task to raise on a failed job")
