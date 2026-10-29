"""Internal helper: raw HTTP for `browser_task`.

`anakin-sdk` 0.2 wraps every endpoint this package uses except the AI
browser task (`POST /ai/evaluate`, polled at `GET /ai/jobs/:id`), so that
one task calls the REST API directly with the same base URL and `X-API-Key`
convention as the SDK. Not part of the public API.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

POLL_INTERVAL_SECONDS = 3.0
# Browser AI tasks are hard-capped server-side at ~330s, so the poll window
# must outlast the longest legitimate run (6 minutes total).
POLL_MAX_ATTEMPTS = 120

#: Replaces a monitor's webhook signing secret in task outputs.
REDACTED = "[redacted: view it in the Anakin dashboard]"


class AnakinHTTPError(RuntimeError):
    """Raised for a non-2xx response from a raw Anakin HTTP call.

    Anakin returns either a flat `{"error": "msg", "code": "CODE"}` body or a
    nested `{"error": {"code": ..., "message": ..., ...}}` envelope.
    """

    def __init__(self, method: str, path: str, response: httpx.Response) -> None:
        self.status_code = response.status_code
        self.code: str | None = None
        self.details: dict[str, Any] | None = None
        message = f"{method} {path} failed ({response.status_code})"

        try:
            body = response.json()
        except ValueError:
            body = None

        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                # Wire's nested envelope.
                message = err.get("message", message)
                self.code = err.get("code")
                self.details = err
            elif isinstance(err, str):
                # Legacy flat envelope.
                message = err
                self.code = body.get("code")

        super().__init__(message)


def request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Issue one request against `client` and return the parsed JSON body.

    Raises `AnakinHTTPError` on a non-2xx response.
    """
    response = client.request(method, path, json=json, params=params)
    if response.is_error:
        raise AnakinHTTPError(method, path, response)
    if not response.content:
        return {}
    return response.json()


def poll(
    client: httpx.Client,
    path: str,
    *,
    is_terminal: Callable[[dict[str, Any]], bool],
    max_attempts: int = POLL_MAX_ATTEMPTS,
    interval_seconds: float = POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Poll `GET path` until `is_terminal(body)` is true, at a fixed interval."""
    for _ in range(max_attempts):
        body = request(client, "GET", path)
        if is_terminal(body):
            return body
        time.sleep(interval_seconds)
    raise TimeoutError(
        f"Polling {path} did not reach a terminal state after "
        f"{max_attempts * interval_seconds:.0f}s ({max_attempts} attempts)."
    )
