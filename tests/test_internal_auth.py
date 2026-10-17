"""The platform's one service-to-service check (smart_llm.internal_auth)."""

from collections.abc import Iterator

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from smart_llm.internal_auth import (
    INTERNAL_KEY_HEADER,
    internal_headers,
    is_internal_caller,
    require_internal_key,
)

KEY = "a-real-internal-key-value-for-tests-0000"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("INTERNAL_API_KEY", KEY)
    app = FastAPI()

    @app.get("/internal", dependencies=[Depends(require_internal_key)])
    async def internal() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as c:
        yield c


def test_right_key_is_accepted(client: TestClient) -> None:
    assert (
        client.get("/internal", headers={INTERNAL_KEY_HEADER: KEY}).status_code == 200
    )


@pytest.mark.parametrize(
    "headers", [{}, {INTERNAL_KEY_HEADER: "wrong"}, {"X-API-Key": KEY}]
)
def test_missing_wrong_or_legacy_header_is_401(
    client: TestClient, headers: dict[str, str]
) -> None:
    assert client.get("/internal", headers=headers).status_code == 401


def test_bearer_is_not_an_internal_key(client: TestClient) -> None:
    assert (
        client.get("/internal", headers={"Authorization": f"Bearer {KEY}"}).status_code
        == 401
    )


def test_no_key_configured_fails_closed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INTERNAL_API_KEY")
    resp = client.get("/internal", headers={INTERNAL_KEY_HEADER: ""})
    assert resp.status_code == 500


def test_empty_key_never_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_API_KEY", "")
    assert is_internal_caller("") is False
    assert is_internal_caller(None) is False


def test_internal_headers_carry_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_API_KEY", KEY)
    assert internal_headers() == {INTERNAL_KEY_HEADER: KEY}
