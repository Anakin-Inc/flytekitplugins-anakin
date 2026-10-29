"""Unit tests for the Anakin tasks.

SDK-backed tasks get a mocked `anakin.Anakin` client that returns real
`anakin.models` objects. Tasks are called the way a workflow calls them
(keyword arguments, flytekit local execution), so every test also runs the
inputs and outputs through flytekit's type engine. `browser_task` gets a fake
`httpx.Client`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from anakin.models import (
    AgenticSearchData,
    AgenticSearchResult,
    AIVisibilitySearch,
    AIVisibilitySource,
    BrowserSession,
    CrawlResult,
    Document,
    MapResult,
    Monitor,
    MonitorRun,
    SearchResult,
    SearchResultItem,
    WireActionMatch,
    WireBuildRequest,
    WireCatalog,
    WireCatalogDetail,
    WireLoginResult,
    WireResult,
)

from flytekitplugins.anakin import (
    agentic_search,
    ai_visibility_search,
    ai_visibility_sources,
    browser_task,
    crawl_site,
    map_site,
    monitor_changes,
    monitor_control,
    monitor_create,
    monitor_get,
    monitor_list,
    scrape_url,
    search,
    session_delete,
    session_list,
    wire_build,
    wire_build_status,
    wire_catalog,
    wire_catalogs,
    wire_discover,
    wire_identities,
    wire_login,
    wire_read_action,
    wire_write_action,
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr("flytekitplugins.anakin.tasks._client", lambda: mock)
    return mock


# ─── Scrape and search ──────────────────────────────────────────────────────


def test_scrape_url(client: MagicMock) -> None:
    client.scrape.return_value = Document.model_validate(
        {
            "id": "job_1",
            "url": "https://example.com",
            "status": "completed",
            "markdown": "# Hello",
            "generatedJson": {"title": "Hello", "price": None},
            "createdAt": "2026-10-16T10:00:00Z",
        }
    )

    result = scrape_url(url="https://example.com", country="gb", use_browser=True)

    assert isinstance(result, Document)
    assert result.markdown == "# Hello"
    assert result.generated_json == {"title": "Hello", "price": None}
    client.scrape.assert_called_once_with(
        "https://example.com",
        formats=("markdown",),
        country="gb",
        use_browser=True,
        generate_json=False,
        output_schema=None,
        force_fresh=False,
        session_id=None,
        session_name=None,
        poll_timeout=None,
    )


def test_scrape_url_passes_schema_and_formats(client: MagicMock) -> None:
    client.scrape.return_value = Document(id="j", status="completed")
    schema = {"type": "object", "properties": {"price": {"type": ["number", "null"]}}}

    scrape_url(url="https://a.com", output_schema=schema, formats=["markdown", "links"])

    kwargs = client.scrape.call_args.kwargs
    assert kwargs["output_schema"] == schema
    assert kwargs["formats"] == ("markdown", "links")


def test_map_site(client: MagicMock) -> None:
    client.map.return_value = MapResult(id="m1", links=["https://a.com/x"], total_links=1)

    result = map_site(url="https://a.com", depth=1, search="x")

    assert result.links == ["https://a.com/x"]
    assert client.map.call_args.kwargs["depth"] == 1
    assert client.map.call_args.kwargs["search"] == "x"


def test_crawl_site(client: MagicMock) -> None:
    client.crawl.return_value = CrawlResult.model_validate(
        {
            "id": "c1",
            "totalPages": 1,
            "completedPages": 1,
            "results": [{"url": "u", "status": "completed", "markdown": "m"}],
        }
    )

    result = crawl_site(url="https://a.com", include_patterns=["/blog/*"])

    assert result.pages[0].markdown == "m"
    assert client.crawl.call_args.kwargs["include_patterns"] == ["/blog/*"]
    assert client.crawl.call_args.kwargs["exclude_patterns"] == ()


def test_search(client: MagicMock) -> None:
    client.search.return_value = SearchResult(
        id="s1", results=[SearchResultItem(url="https://example.com", title="Example")]
    )

    result = search(prompt="what is anakin", limit=3)

    assert result.results[0].url == "https://example.com"
    client.search.assert_called_once_with("what is anakin", limit=3)


def test_agentic_search(client: MagicMock) -> None:
    client.agentic_search.return_value = AgenticSearchResult(
        id="a1", status="completed", generated_json=AgenticSearchData(summary="done")
    )

    result = agentic_search(prompt="research x", schema={"type": "object"})

    assert result.generated_json is not None
    assert result.generated_json.summary == "done"
    client.agentic_search.assert_called_once_with(
        "research x", use_browser=True, schema={"type": "object"}, poll_timeout=None
    )


# ─── Wire ───────────────────────────────────────────────────────────────────


def test_wire_discover(client: MagicMock) -> None:
    client.wire.discover.return_value = [WireActionMatch(action_id="amazon.search", mode="read")]

    result = wire_discover(q="search amazon", limit=3)

    assert result[0].action_id == "amazon.search"
    client.wire.discover.assert_called_once_with("search amazon", catalog=None, limit=3)


def test_wire_catalogs(client: MagicMock) -> None:
    client.wire.catalogs.return_value = [WireCatalog(id="c1", slug="amazon", name="Amazon")]

    result = wire_catalogs()

    assert result[0].slug == "amazon"


def test_wire_catalog(client: MagicMock) -> None:
    client.wire.catalog.return_value = WireCatalogDetail.model_validate(
        {
            "catalog": {"id": "c1", "slug": "amazon", "name": "Amazon"},
            "actions": [],
            "login_input_schema": [{"name": "email", "default": None}],
        }
    )

    result = wire_catalog(slug="amazon")

    assert result.catalog.slug == "amazon"
    assert result.login_input_schema == [{"name": "email", "default": None}]
    client.wire.catalog.assert_called_once_with("amazon")


def test_wire_read_action_passes_credential(client: MagicMock) -> None:
    client.wire.run.return_value = WireResult(
        job_id="j1", status="completed", data={"price": 9, "sale": None}
    )

    result = wire_read_action(
        action_id="amazon.get_product", params={"asin": "B0"}, credential_id="cred_1"
    )

    assert result.data == {"price": 9, "sale": None}
    client.wire.run.assert_called_once_with(
        "amazon.get_product",
        {"asin": "B0"},
        credential_id="cred_1",
        identity_id=None,
        poll_timeout=None,
    )


def test_wire_read_action_defaults_params(client: MagicMock) -> None:
    client.wire.run.return_value = WireResult(status="completed")

    wire_read_action(action_id="x.list")

    assert client.wire.run.call_args.args == ("x.list", {})


def test_wire_write_action_runs_benign_action(client: MagicMock) -> None:
    client.wire.run.return_value = WireResult(status="completed")

    wire_write_action(action_id="shop.add_to_cart", params={"sku": "1"})

    client.wire.run.assert_called_once()


def test_wire_write_action_refuses_payment(client: MagicMock) -> None:
    with pytest.raises(Exception, match="payments or fund transfers"):
        wire_write_action(action_id="shop.checkout")
    client.wire.run.assert_not_called()


def test_wire_identities(client: MagicMock) -> None:
    client.wire.identities.return_value = []

    assert wire_identities(catalog_id="cat_1") == []
    client.wire.identities.assert_called_once_with(catalog_id="cat_1")


def test_wire_login(client: MagicMock) -> None:
    client.wire.login.return_value = WireLoginResult(
        status="ok", identity_id="i1", credential_id="cred_1"
    )

    result = wire_login(catalog_slug="neb", params={"email": "a@b.c", "password": "x"})

    assert result.credential_id == "cred_1"
    client.wire.login.assert_called_once_with(
        "neb",
        {"email": "a@b.c", "password": "x"},
        identity_name=None,
        source_id=None,
        source_ref=None,
    )


def test_wire_build(client: MagicMock) -> None:
    client.wire.build.return_value = WireBuildRequest(id="b1", status="pending")

    result = wire_build(website_url="https://example.com", goal="list products")

    assert result.status == "pending"
    client.wire.build.assert_called_once_with(
        "https://example.com", "list products", catalog_id=None, visibility="private", force=False
    )


def test_wire_build_refuses_payment(client: MagicMock) -> None:
    with pytest.raises(Exception, match="payments or fund transfers"):
        wire_build(website_url="https://shop.com", goal="pay now for the order")
    client.wire.build.assert_not_called()


def test_wire_build_status(client: MagicMock) -> None:
    client.wire.get_build.return_value = WireBuildRequest(id="b1", status="success")

    assert wire_build_status(build_id="b1").status == "success"


# ─── Monitors ───────────────────────────────────────────────────────────────


def _monitor(**extra: Any) -> Monitor:
    return Monitor.model_validate(
        {"id": "mon_1", "url": "https://a.com", "createdAt": "2026-10-28T10:00:00Z", **extra}
    )


def test_monitor_create_maps_options_and_redacts_secret(client: MagicMock) -> None:
    client.monitors.create.return_value = _monitor(alertWebhookSecret="whsec_live")

    result = monitor_create(
        url="https://a.com", interval_minutes=60, ai_mode=True, alert_webhook_url="https://hook"
    )

    assert result.id == "mon_1"
    assert result.alert_webhook_secret is not None
    assert result.alert_webhook_secret.startswith("[redacted")
    assert "whsec_live" not in result.model_dump_json()
    args, kwargs = client.monitors.create.call_args
    assert args == ("https://a.com", 60)
    assert kwargs["ai_mode"] is True
    assert kwargs["alert_webhook_url"] == "https://hook"
    assert "output_schema" not in kwargs


def test_monitor_list_and_get_redact(client: MagicMock) -> None:
    client.monitors.get.return_value = _monitor(alertWebhookSecret="s")
    client.monitors.list.return_value = [_monitor(alertWebhookSecret="s"), _monitor()]

    one = monitor_get(monitor_id="mon_1")
    many = monitor_list()

    assert one.alert_webhook_secret is not None
    assert one.alert_webhook_secret.startswith("[redacted")
    assert many[0].alert_webhook_secret is not None
    assert many[0].alert_webhook_secret.startswith("[redacted")
    assert many[1].alert_webhook_secret is None


def test_monitor_changes(client: MagicMock) -> None:
    client.monitors.changes.return_value = []

    assert monitor_changes(monitor_id="mon_1") == []
    client.monitors.changes.assert_called_once_with("mon_1")


@pytest.mark.parametrize("action", ["pause", "resume"])
def test_monitor_control_pause_resume(client: MagicMock, action: str) -> None:
    getattr(client.monitors, action).return_value = _monitor(alertWebhookSecret="s")

    result = monitor_control(monitor_id="mon_1", action=action)

    assert result is not None
    assert result["id"] == "mon_1"
    assert result["alert_webhook_secret"].startswith("[redacted")
    getattr(client.monitors, action).assert_called_once_with("mon_1")


def test_monitor_control_run_now(client: MagicMock) -> None:
    client.monitors.run_now.return_value = MonitorRun(success=True, job_id="j1")

    result = monitor_control(monitor_id="mon_1", action="run_now")

    assert result == {"success": True, "job_id": "j1", "message": None}


def test_monitor_control_delete(client: MagicMock) -> None:
    assert monitor_control(monitor_id="mon_1", action="delete") is None
    client.monitors.delete.assert_called_once_with("mon_1")


def test_monitor_control_rejects_unknown_action(client: MagicMock) -> None:
    with pytest.raises(Exception, match="Unknown monitor action"):
        monitor_control(monitor_id="mon_1", action="explode")


# ─── AI visibility ──────────────────────────────────────────────────────────


def test_ai_visibility_sources(client: MagicMock) -> None:
    client.ai_visibility.sources.return_value = [
        AIVisibilitySource.model_validate({"slug": "chatgpt", "label": "ChatGPT"})
    ]

    assert ai_visibility_sources()[0].slug == "chatgpt"


def _visibility_result() -> AIVisibilitySearch:
    return AIVisibilitySearch.model_validate(
        {
            "search_id": "v1",
            "status": "completed",
            "results": [{"source": "chatgpt", "status": "completed", "full_content": "long"}],
        }
    )


def test_ai_visibility_search_strips_full_content(client: MagicMock) -> None:
    client.ai_visibility.search.return_value = _visibility_result()

    result = ai_visibility_search(query="best scraping api", sources=["chatgpt"])

    assert result.results[0].full_content is None
    client.ai_visibility.search.assert_called_once_with(
        "best scraping api", sources=["chatgpt"], country="us", poll_timeout=None
    )


def test_ai_visibility_search_keeps_full_content(client: MagicMock) -> None:
    client.ai_visibility.search.return_value = _visibility_result()

    result = ai_visibility_search(query="q", include_full_content=True)

    assert result.results[0].full_content == "long"


# ─── Sessions and browser tasks ─────────────────────────────────────────────


def test_session_list(client: MagicMock) -> None:
    client.sessions.list.return_value = [BrowserSession.model_validate({"id": "s1", "name": "amz"})]

    result = session_list(domain="amazon.com")

    assert result[0].id == "s1"
    client.sessions.list.assert_called_once_with(domain="amazon.com")


def test_session_delete(client: MagicMock) -> None:
    session_delete(session_id="s1")
    client.sessions.delete.assert_called_once_with("s1")


def _fake_http(*bodies: Any) -> MagicMock:
    http = MagicMock()
    http.__enter__.return_value = http
    http.__exit__.return_value = False
    responses = []
    for body in bodies:
        response = MagicMock(is_error=False, content=b"x")
        response.json.return_value = body
        responses.append(response)
    http.request.side_effect = responses
    return http


def test_browser_task_polls_until_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    http = _fake_http(
        {"workflow_id": "wf_1"},
        {"status": "running"},
        {
            "status": "completed",
            "result": {"success": True, "result": {"x": 1, "y": None}, "run_id": "r1"},
        },
    )
    monkeypatch.setattr("flytekitplugins.anakin.tasks._http_client", lambda: http)
    monkeypatch.setattr("flytekitplugins.anakin._http.time.sleep", lambda _s: None)

    result = browser_task(prompt="find the cheapest TV", url="https://shop.com", max_steps=5)

    assert result["success"] is True
    assert result["result"] == {"x": 1, "y": None}
    assert result["run_id"] == "r1"
    method, path = http.request.call_args_list[0].args
    assert (method, path) == ("POST", "/ai/evaluate")
    assert http.request.call_args_list[0].kwargs["json"] == {
        "prompt": "find the cheapest TV",
        "async": True,
        "url": "https://shop.com",
        "max_steps": 5,
    }
    assert http.request.call_args_list[1].args == ("GET", "/ai/jobs/wf_1")


def test_browser_task_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    http = _fake_http({"workflow_id": "wf_1"}, {"status": "failed", "error": "site unreachable"})
    monkeypatch.setattr("flytekitplugins.anakin.tasks._http_client", lambda: http)

    with pytest.raises(Exception, match="site unreachable"):
        browser_task(prompt="do something")


def test_browser_task_refuses_payment() -> None:
    with pytest.raises(Exception, match="payments or fund transfers"):
        browser_task(prompt="checkout and buy now")


def test_browser_task_needs_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANAKIN_API_KEY", raising=False)

    with pytest.raises(Exception, match="needs an Anakin API key"):
        browser_task(prompt="read the headline")
