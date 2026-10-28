"""Example Flyte workflows using flytekitplugins-anakin.

Run locally (no Flyte cluster needed). ``scrape_pages_wf`` and
``wire_lookup_wf`` work without an API key on Anakin's free per-IP allowance:

    pyflyte run example_workflows/example_anakin.py scrape_pages_wf \\
        --urls '["https://example.com", "https://anakin.io"]'
    pyflyte run example_workflows/example_anakin.py wire_lookup_wf --q "search products on amazon"

``research_wf`` needs a key (``ANAKIN_API_KEY`` locally, or the
``anakin/api-key`` Flyte secret on a cluster):

    ANAKIN_API_KEY=ask_... pyflyte run example_workflows/example_anakin.py research_wf \\
        --topic "web scraping APIs for AI agents"

Add ``--remote`` to run on a cluster after creating the secret.
"""

from __future__ import annotations

import functools

from anakin.models import Document, SearchResult, WireActionMatch
from flytekit import map_task, task, workflow

from flytekitplugins.anakin import (
    agentic_search,
    scrape_url,
    search,
    wire_catalog,
    wire_discover,
)


@task
def summarize_pages(docs: list[Document]) -> list[str]:
    """Downstream tasks get typed `anakin.models` objects, not raw JSON."""
    return [f"{doc.url}: {len(doc.markdown or '')} chars of markdown" for doc in docs]


# map_task maps over `url` and needs every other input bound, defaults included.
scrape_markdown = functools.partial(
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
def scrape_pages_wf(urls: list[str]) -> list[str]:
    """Scrape many pages in parallel with Flyte's map_task, then post-process them."""
    docs = map_task(scrape_markdown)(url=urls)
    return summarize_pages(docs=docs)


@task
def describe_matches(matches: list[WireActionMatch]) -> list[str]:
    return [f"{m.action_id} ({m.mode}, {m.credits} credits)" for m in matches]


@task
def first_catalog(matches: list[WireActionMatch]) -> str:
    return (matches[0].catalog_slug or "") if matches else ""


@workflow
def wire_lookup_wf(q: str) -> list[str]:
    """Find pre-built Wire actions for a task described in plain language."""
    matches = wire_discover(q=q, limit=3)
    wire_catalog(slug=first_catalog(matches=matches))
    return describe_matches(matches=matches)


@task
def to_brief(quick: SearchResult, page: Document) -> str:
    sources = "\n".join(f"- {r.title}: {r.url}" for r in quick.results)
    return f"Sources:\n{sources}\n\nFirst source, {len(page.markdown or '')} chars scraped."


@task
def top_url(quick: SearchResult) -> str:
    return quick.results[0].url


@workflow
def research_wf(topic: str) -> str:
    """Search the web, scrape the top hit, and run a deeper agentic research pass."""
    quick = search(prompt=topic, limit=5)
    page = scrape_url(url=top_url(quick=quick))
    agentic_search(prompt=topic)
    return to_brief(quick=quick, page=page)
