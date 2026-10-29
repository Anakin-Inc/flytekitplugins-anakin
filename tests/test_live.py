"""Live calls to api.anakin.io. Skipped unless ANAKIN_LIVE_TESTS=1.

The keyless tests (scrape, Wire discovery and catalog) need no API key. The
rest only read account state and run when ANAKIN_API_KEY is set too.
"""

from __future__ import annotations

import os

import pytest
from flytekit import workflow

from flytekitplugins.anakin import (
    ai_visibility_sources,
    monitor_list,
    scrape_url,
    session_list,
    wire_catalog,
    wire_catalogs,
    wire_discover,
    wire_identities,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("ANAKIN_LIVE_TESTS") != "1",
    reason="set ANAKIN_LIVE_TESTS=1 to call the live API",
)

needs_key = pytest.mark.skipif(not os.environ.get("ANAKIN_API_KEY"), reason="needs ANAKIN_API_KEY")


def test_keyless_scrape_in_a_workflow() -> None:
    @workflow
    def wf() -> str:
        return scrape_url(url="https://example.com").markdown  # type: ignore[no-any-return]

    assert "documentation examples" in wf()


def test_keyless_wire_discovery() -> None:
    matches = wire_discover(q="search products on amazon", limit=3)
    assert matches and matches[0].action_id

    catalogs = wire_catalogs()
    assert len(catalogs) > 0

    detail = wire_catalog(slug=matches[0].catalog_slug)
    assert detail.actions


@needs_key
def test_account_reads() -> None:
    assert ai_visibility_sources()
    assert isinstance(wire_identities(), list)
    assert isinstance(session_list(), list)
    for monitor in monitor_list():
        assert not monitor.alert_webhook_secret or monitor.alert_webhook_secret.startswith(
            "[redacted"
        )
