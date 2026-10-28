"""Unit tests for the raw-HTTP helpers browser_task uses (`flytekitplugins.anakin._http`).

They run `request`, `poll` and `AnakinHTTPError` against a fake client, with no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from flytekitplugins.anakin._http import AnakinHTTPError, poll, request


@dataclass
class FakeResponse:
    status_code: int
    _body: Any = None
    content: bytes = b"{}"

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def json(self) -> Any:
        return self._body


def _ok(body: Any) -> FakeResponse:
    return FakeResponse(status_code=200, _body=body, content=b"x")


def _err(status_code: int, body: Any) -> FakeResponse:
    return FakeResponse(status_code=status_code, _body=body, content=b"x")


def test_request_returns_json_body_on_success() -> None:
    client = MagicMock()
    client.request.return_value = _ok({"id": "abc"})

    result = request(client, "GET", "/wire/catalog")

    assert result == {"id": "abc"}
    client.request.assert_called_once_with("GET", "/wire/catalog", json=None, params=None)


def test_request_returns_empty_dict_for_empty_body() -> None:
    client = MagicMock()
    client.request.return_value = FakeResponse(status_code=200, content=b"")

    assert request(client, "DELETE", "/monitors/mon_1") == {}


def test_request_raises_on_flat_error_envelope() -> None:
    client = MagicMock()
    client.request.return_value = _err(404, {"error": "not found", "code": "NOT_FOUND"})

    with pytest.raises(AnakinHTTPError) as exc_info:
        request(client, "GET", "/monitors/missing")

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "NOT_FOUND"
    assert "not found" in str(exc_info.value)


def test_request_raises_on_nested_wire_error_envelope() -> None:
    client = MagicMock()
    client.request.return_value = _err(
        401,
        {
            "error": {
                "code": "AUTH_REQUIRED",
                "message": "connect your account",
                "connect_url": "https://x",
            }
        },
    )

    with pytest.raises(AnakinHTTPError) as exc_info:
        request(client, "POST", "/holocron/task")

    assert exc_info.value.code == "AUTH_REQUIRED"
    assert exc_info.value.details is not None
    assert exc_info.value.details["connect_url"] == "https://x"
    assert "connect your account" in str(exc_info.value)


def test_poll_returns_once_terminal() -> None:
    client = MagicMock()
    client.request.side_effect = [
        _ok({"status": "running"}),
        _ok({"status": "running"}),
        _ok({"status": "completed", "id": "s_1"}),
    ]

    result = poll(
        client,
        "/ai-visibility/search/s_1",
        is_terminal=lambda body: body.get("status") != "running",
        interval_seconds=0,
    )

    assert result == {"status": "completed", "id": "s_1"}
    assert client.request.call_count == 3


def test_poll_raises_timeout_when_never_terminal() -> None:
    client = MagicMock()
    client.request.return_value = _ok({"status": "running"})

    with pytest.raises(TimeoutError):
        poll(
            client,
            "/ai-visibility/search/s_1",
            is_terminal=lambda body: body.get("status") == "completed",
            max_attempts=2,
            interval_seconds=0,
        )
