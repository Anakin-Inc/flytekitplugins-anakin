"""Example Flyte workflow for the Anakin tasks.

Not part of the installable package (not under ``flytekitplugins/``) —
provided for reference, the same way flytekit's own plugin repo ships
runnable examples in each plugin's README. Requires an Anakin API key
available either as the Flyte secret ``group="anakin", key="api-key"``
(see README.md for how to create it) or as an ``ANAKIN_API_KEY``
environment variable when running locally with ``pyflyte run``.

Run locally (no Flyte backend needed):

    ANAKIN_API_KEY=ask-... pyflyte run example_workflows/example_anakin.py \\
        anakin_research_wf --topic "developments in AI agents"
"""

from __future__ import annotations

from flytekit import workflow

from flytekitplugins.anakin import agentic_search, scrape_url, search
from anakin.models import AgenticSearchResult, Document, SearchResult


@workflow
def anakin_research_wf(topic: str = "developments in AI agents") -> AgenticSearchResult:
    """Scrape a reference page, run a quick search, then a deeper agentic
    research pass — chained the way a real research pipeline would use
    these three endpoints together."""
    doc: Document = scrape_url(url="https://anakin.io/docs")
    quick: SearchResult = search(prompt=topic, limit=5)
    return agentic_search(prompt=topic, use_browser=True)


if __name__ == "__main__":
    print(anakin_research_wf(topic="developments in AI agents"))
