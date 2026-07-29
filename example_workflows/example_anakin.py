"""Example Flyte workflows for the Anakin tasks.

Not part of the installable package (not under ``flytekitplugins/``) —
provided for reference, the same way flytekit's own plugin repo ships
runnable examples in each plugin's README. Requires an Anakin API key
available either as the Flyte secret ``group="anakin"``, ``key="api-key"``
(see README.md for how to create it) or as an ``ANAKIN_API_KEY``
environment variable when running locally with ``pyflyte run``.

Run locally (no Flyte backend needed):

    ANAKIN_API_KEY=ask-... pyflyte run example_workflows/example_anakin.py \\
        anakin_research_wf --topic "developments in AI agents"

    ANAKIN_API_KEY=ask-... pyflyte run example_workflows/example_anakin.py \\
        anakin_wire_and_monitoring_wf --website_url "https://example.com"
"""

from __future__ import annotations

from typing import Any

from flytekit import workflow

from anakin.models import AgenticSearchResult, Document, SearchResult
from flytekitplugins.anakin import (
    agentic_search,
    ai_visibility_search,
    monitor_create,
    scrape_url,
    search,
    wire_discover,
)


@workflow
def anakin_research_wf(topic: str = "developments in AI agents") -> AgenticSearchResult:
    """Scrape a reference page, run a quick search, then a deeper agentic
    research pass — chained the way a real research pipeline would use
    these three endpoints together."""
    doc: Document = scrape_url(url="https://anakin.io/docs")
    quick: SearchResult = search(prompt=topic, limit=5)
    return agentic_search(prompt=topic, use_browser=True)


@workflow
def anakin_wire_and_monitoring_wf(
    website_url: str = "https://example.com",
) -> dict[str, Any]:
    """A second pipeline exercising the newer capability groups this
    package added beyond the original scrape/search/agentic_search trio:
    Wire action discovery, a scheduled website monitor, and an AI-visibility
    brand check — three of the 12 raw-HTTP tasks (no anakin-sdk model
    backs their output, so each returns a plain ``dict``).

    Discovers candidate Wire actions for the site, creates a low-frequency
    monitor watching it for changes, and asks multiple AI answer engines
    what they say about it — independent steps, run for illustration rather
    than because one feeds the next.
    """
    candidates: dict[str, Any] = wire_discover(q=f"extract data from {website_url}", limit=3)
    monitor: dict[str, Any] = monitor_create(url=website_url, interval_minutes=60)
    visibility: dict[str, Any] = ai_visibility_search(query=f"What is {website_url}?")
    return {"wire_candidates": candidates, "monitor": monitor, "ai_visibility": visibility}


if __name__ == "__main__":
    print(anakin_research_wf(topic="developments in AI agents"))
