"""Minimal HTTP helper for Anakin API endpoints not (yet) covered by
``anakin-sdk`` v0.1.0.

``anakin-sdk``'s ``Anakin`` client (see ``anakin-py/src/anakin/client.py``,
read in full for this package) implements ``scrape``, ``map``, ``crawl``,
``search``, ``agentic_search``, ``wire`` (run one pre-built action), and
``sessions.list``/``sessions.delete``. It does **not** implement Wire
discovery/catalog/identities/login/build, website monitoring, AI visibility,
or AI browser automation — confirmed by reading the SDK's source directly,
not assumed. The tasks in ``tasks.py`` that need those endpoints call the
REST API here with ``httpx`` directly, reusing the same auth header,
dual-shape error tolerance, and retry/poll backoff ``anakin._http.HttpClient``
itself uses internally, so behavior is consistent across every task in this
package regardless of whether a given one happens to route through the SDK.

Every path, verb, and poll target below is read from
``anakin-mcp/src/client.ts`` (Anakin's own MCP server — a second, independent
implementation hitting the same REST API), not invented:

- Wire discovery: ``GET /wire/resolve``, ``GET /wire/catalog[/:slug]``,
  ``GET /wire/identities``, ``POST /wire/login``, ``POST /wire/build-request``.
- Monitors: ``POST /monitors``, ``GET /monitors[/:id]``,
  ``GET /monitors/:id/changes``, ``POST /monitors/:id/{pause,resume,run}``,
  ``DELETE /monitors/:id``.
- AI visibility: ``GET /ai-visibility/sources``,
  ``POST /ai-visibility/search`` + poll ``GET /ai-visibility/search/:id``.
- Browser automation: ``POST /ai/evaluate`` (async) + poll
  ``GET /ai/jobs/:id``.

Not part of this package's public API — imported only by ``tasks.py``.
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable, Optional

import httpx

DEFAULT_TIMEOUT = 30.0

#: anakin-mcp polls every 3s for up to 60 attempts (3 minutes total) for
#: monitor/ai-visibility style jobs — see ``POLL_INTERVAL_MS`` /
#: ``POLL_MAX_ATTEMPTS`` in anakin-mcp/src/client.ts.
DEFAULT_POLL_INTERVAL = 3.0
DEFAULT_POLL_TIMEOUT = 180.0

#: Browser AI tasks are hard-capped server-side at ~330s, so anakin-mcp polls
#: them for up to 6 minutes (``BROWSER_TASK_POLL_MAX_ATTEMPTS = 120``) rather
#: than the usual 3 — mirrored here as this module's browser_task default.
BROWSER_TASK_POLL_TIMEOUT = 360.0

MAX_RETRIES = 4
RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


class AnakinAPIError(RuntimeError):
    """Raised for a non-2xx response, a network failure after retries, or a
    terminal-failure job state from a raw (non-SDK) Anakin API call.

    Deliberately distinct from ``anakin.errors.AnakinError`` (anakin-sdk's
    own error hierarchy): that hierarchy is raised only for calls made
    *through* the SDK client, and this module doesn't reimplement its full
    status-code-to-exception-subclass mapping — callers that need
    fine-grained handling (e.g. detecting a Wire ``AUTH_REQUIRED`` the way
    ``anakin.errors.WireAuthRequiredError`` does) can inspect ``.code``.
    """

    def __init__(
        self, message: str, *, status_code: Optional[int] = None, code: Optional[str] = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def as_dict(body: Any) -> dict[str, Any]:
    """Normalize a JSON response to ``dict[str, Any]`` for Flyte task output
    typing. Every collection endpoint this module calls is documented (or
    observed, via ``anakin-mcp``) to wrap its results under a key (e.g.
    ``sessions.list``'s ``{"sessions": [...]}"``); this only guards against
    an endpoint returning a bare JSON array by wrapping it under ``"items"``
    so callers always get a dict back.
    """
    if isinstance(body, dict):
        return body
    return {"items": body}


def _extract_error(body: Any, fallback: str) -> tuple[str, Optional[str]]:
    """Tolerate both shapes Anakin's API returns errors in — the legacy flat
    ``{"error": "msg", "code": "..."}`` and Wire's nested envelope
    ``{"error": {"code": ..., "message": ...}}`` — the same two shapes
    ``anakin._http._extract_error`` tolerates for SDK-covered endpoints."""
    if not isinstance(body, dict):
        return fallback, None
    err = body.get("error")
    if isinstance(err, dict):
        return err.get("message", fallback), err.get("code")
    if isinstance(err, str):
        return body.get("message", fallback), err
    return body.get("message", fallback), None


def _parse_retry_after(response: httpx.Response) -> Optional[float]:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _sleep_with_backoff(attempt: int, *, retry_after: Optional[float]) -> None:
    if retry_after is not None and retry_after > 0:
        delay = retry_after
    else:
        # 0.25s, 0.5s, 1s, 2s with full jitter — same schedule as
        # anakin._http.HttpClient._sleep_with_backoff.
        base = 0.25 * (2 ** (attempt - 1))
        delay = random.uniform(0, base)
    time.sleep(delay)


def request(
    method: str,
    path: str,
    *,
    api_key: str,
    base_url: str,
    json: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """One HTTP call to the Anakin API, with exponential-backoff retry on
    429/502/503/504 (honoring ``Retry-After``) and on network errors — the
    same retry policy ``anakin._http.HttpClient`` applies to SDK-covered
    endpoints, reimplemented here since that class is package-private to
    ``anakin-sdk`` (``anakin._http`` — not part of its public API)."""
    url = base_url.rstrip("/") + path
    headers = {
        "X-API-Key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    attempt = 0
    with httpx.Client(timeout=timeout) as client:
        while True:
            attempt += 1
            try:
                response = client.request(method, url, json=json, params=params, headers=headers)
            except httpx.RequestError as exc:
                if attempt > MAX_RETRIES:
                    raise AnakinAPIError(
                        f"Network error after {attempt} attempts calling {method} {path}: {exc}"
                    ) from exc
                _sleep_with_backoff(attempt, retry_after=None)
                continue

            if response.status_code in RETRYABLE_STATUS and attempt <= MAX_RETRIES:
                _sleep_with_backoff(attempt, retry_after=_parse_retry_after(response))
                continue

            if 200 <= response.status_code < 300:
                return response.json() if response.content else {}

            try:
                body = response.json() if response.content else {}
            except ValueError:
                body = {}
            message, code = _extract_error(body, response.reason_phrase or "Unknown error")
            raise AnakinAPIError(
                f"{method} {path} failed ({response.status_code}): {message}",
                status_code=response.status_code,
                code=code,
            )


def poll(
    path: str,
    *,
    api_key: str,
    base_url: str,
    is_terminal: Callable[[dict[str, Any]], bool],
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    poll_timeout: float = DEFAULT_POLL_TIMEOUT,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Poll ``GET path`` at a fixed interval until ``is_terminal(body)`` is
    true — the same fixed-interval polling shape anakin-mcp's own
    ``pollJob``/``pollWireJob``/``browserTask`` loops use (see
    ``anakin-mcp/src/client.ts``), bounded by ``poll_timeout`` wall-clock
    seconds."""
    deadline = time.monotonic() + poll_timeout
    while True:
        body = request("GET", path, api_key=api_key, base_url=base_url, timeout=timeout)
        if not isinstance(body, dict):
            body = as_dict(body)
        if is_terminal(body):
            return body
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AnakinAPIError(
                f"Polling {path} did not reach a terminal state within {poll_timeout}s"
            )
        time.sleep(min(poll_interval, remaining))
