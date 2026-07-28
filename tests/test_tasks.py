"""Unit tests for the Anakin flytekit tasks.

Mocks `flytekitplugins.anakin.tasks.Anakin` (the SDK client class) entirely
— these test the task <-> anakin-sdk wiring (kwargs passed through, the
SDK's Pydantic model returned as-is), not the SDK or Flyte's runtime
themselves. Tasks are called directly, which is flytekit's own supported
pattern for exercising `@task` functions without a running Flyte backend
("local execution" — see flytekit's testing docs). Requires `flytekit` and
`anakin-sdk` installed to *run*; see SUBMIT.md for why that wasn't
exercised in this environment.
"""

from __future__ import annotations

from unittest.mock import patch

from anakin.models import AgenticSearchResult, Document, SearchResult

from flytekitplugins.anakin.tasks import (
    ANAKIN_SECRET_GROUP,
    ANAKIN_SECRET_KEY,
    DEFAULT_ANAKIN_BASE_URL,
    agentic_search,
    scrape_url,
    search,
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
