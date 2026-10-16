"""The shared current-user dependency (smart_llm.current_user).

Pins the platform-wide contract every service swaps to: 401 (+ WWW-Authenticate)
for every token failure, X-Auth-Error on expiry, company_id -> org -> cid, the
admin rules, revocation, and that the service's RLS stamp sees the user. Tokens
are RS256; HS256 is rejected.
"""

import time
import uuid
from collections.abc import Iterator

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from smart_llm import current_user as cu
from smart_llm.current_user import (
    CurrentUser,
    current_user_dependency,
    optional_current_user_dependency,
    user_from_claims,
)

SECRET = "a-real-32byte-plus-shared-secret-value!!"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_PEM = (
    _KEY.public_key()
    .public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    .decode()
)
USER = uuid.uuid4()
COMPANY = uuid.uuid4()


def _token(**claims: object) -> str:
    payload: dict[str, object] = {
        "sub": str(USER),
        "scope": "full",
        "exp": int(time.time()) + 300,
        "company_id": str(COMPANY),
        "role": "member",
    }
    payload.update(claims)
    return jwt.encode(
        {k: v for k, v in payload.items() if v is not None}, _KEY, algorithm="RS256"
    )


def _hs256_token() -> str:
    return jwt.encode(
        {"sub": str(USER), "scope": "full", "exp": int(time.time()) + 300},
        SECRET,
        algorithm="HS256",
    )


@pytest.fixture(autouse=True)
def _rs256_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_PUBLIC_KEY", PUBLIC_PEM)
    monkeypatch.delenv("JWT_JWKS_URL", raising=False)
    monkeypatch.delenv("JWT_AUDIENCE", raising=False)
    monkeypatch.delenv("JWT_ISSUER", raising=False)


@pytest.fixture
def revoked(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """jti values to treat as revoked."""
    jtis: set[str] = set()

    async def fake(payload: dict[str, object]) -> bool:
        return payload.get("jti") in jtis

    monkeypatch.setattr(cu, "token_is_revoked", fake)
    return jtis


@pytest.fixture
def stamped() -> list[CurrentUser]:
    return []


@pytest.fixture
def client(revoked: set[str], stamped: list[CurrentUser]) -> Iterator[TestClient]:
    app = FastAPI()
    required = current_user_dependency(stamped.append)
    optional = optional_current_user_dependency(stamped.append)

    @app.get("/me")
    async def me(user: CurrentUser = Depends(required)) -> dict[str, object]:
        return {"id": str(user.id), "company": str(user.company_id), "role": user.role}

    @app.get("/maybe")
    async def maybe(user: CurrentUser | None = Depends(optional)) -> dict[str, object]:
        return {"user": str(user.user_id) if user else None}

    with TestClient(app) as c:
        yield c


def _get(client: TestClient, path: str, token: str | None) -> object:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get(path, headers=headers)


# ── the happy path ───────────────────────────────────────────────────────────


def test_valid_token_returns_user_and_stamps_rls(
    client: TestClient, stamped: list[CurrentUser]
) -> None:
    resp = client.get("/me", headers={"Authorization": f"Bearer {_token()}"})
    assert resp.status_code == 200
    assert resp.json() == {"id": str(USER), "company": str(COMPANY), "role": "member"}
    assert [u.user_id for u in stamped] == [USER]


# ── every token failure is 401 + WWW-Authenticate ────────────────────────────


@pytest.mark.parametrize(
    ("token", "detail"),
    [
        (None, "Not authenticated"),
        ("not-a-jwt", "Invalid token"),
        ("wrong_key", "Invalid token"),
        ("hs256", "Invalid token"),
        ("refresh", "Invalid token"),
        ("pre_2fa", "Invalid token"),
        ("no_exp", "Invalid token"),
        ("no_sub", "Invalid token"),
        ("bad_sub", "Invalid token claims"),
        ("bad_company", "Invalid token claims"),
    ],
    ids=[
        "missing",
        "garbage",
        "wrong-key",
        "hs256",
        "refresh-scope",
        "pre2fa-scope",
        "no-exp",
        "no-sub",
        "bad-sub",
        "bad-company",
    ],
)
def test_token_failures_are_401(
    client: TestClient, stamped: list[CurrentUser], token: str | None, detail: str
) -> None:
    variants = {
        "wrong_key": jwt.encode(
            {"sub": str(USER), "scope": "full", "exp": int(time.time()) + 60},
            rsa.generate_private_key(public_exponent=65537, key_size=2048),
            algorithm="RS256",
        ),
        "hs256": _hs256_token(),
        "refresh": _token(scope="refresh"),
        "pre_2fa": _token(scope="pre_2fa"),
        "no_exp": _token(exp=None),
        "no_sub": _token(sub=None),
        "bad_sub": _token(sub="not-a-uuid"),
        "bad_company": _token(company_id="not-a-uuid"),
    }
    resp = _get(client, "/me", variants.get(token or "", token))
    assert resp.status_code == 401
    assert resp.json()["detail"] == detail
    assert resp.headers["WWW-Authenticate"] == "Bearer"
    assert "X-Auth-Error" not in resp.headers
    assert stamped == []


def test_expired_token_is_401_with_x_auth_error(client: TestClient) -> None:
    resp = _get(client, "/me", _token(exp=int(time.time()) - 10))
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Token expired"
    assert resp.headers["WWW-Authenticate"] == "Bearer"
    assert resp.headers["X-Auth-Error"] == "token_expired"


def test_revoked_token_is_401(client: TestClient, revoked: set[str]) -> None:
    revoked.add("j-1")
    resp = _get(client, "/me", _token(jti="j-1"))
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Token has been revoked"
    assert resp.headers["WWW-Authenticate"] == "Bearer"


def test_no_key_configured_fails_closed(
    revoked: set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("JWT_PUBLIC_KEY")
    app = FastAPI()
    dep = current_user_dependency(lambda _u: None)

    @app.get("/me")
    async def me(user: CurrentUser = Depends(dep)) -> dict[str, str]:
        return {"id": str(user.id)}

    with TestClient(app) as c:
        resp = c.get("/me", headers={"Authorization": f"Bearer {_token()}"})
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Server misconfigured: no JWT key"


# ── the optional variant ─────────────────────────────────────────────────────


def test_optional_is_none_without_a_usable_token(
    client: TestClient, stamped: list[CurrentUser]
) -> None:
    assert _get(client, "/maybe", None).json() == {"user": None}
    assert _get(client, "/maybe", "not-a-jwt").json() == {"user": None}
    assert _get(client, "/maybe", _token(exp=int(time.time()) - 10)).json() == {
        "user": None
    }
    assert stamped == []


def test_optional_returns_and_stamps_a_valid_user(
    client: TestClient, stamped: list[CurrentUser]
) -> None:
    assert _get(client, "/maybe", _token()).json() == {"user": str(USER)}
    assert [u.user_id for u in stamped] == [USER]


# ── claims ───────────────────────────────────────────────────────────────────


def _claims(**extra: object) -> dict[str, object]:
    return {"sub": str(USER), **extra}


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ({"company_id": "C", "org": "O", "cid": "X"}, "C"),
        ({"org": "O", "cid": "X"}, "O"),
        ({"cid": "X"}, "X"),
        ({"company_id": "", "org": "O"}, "O"),
        ({}, None),
    ],
    ids=["company_id-first", "then-org", "then-cid", "empty-skipped", "none"],
)
def test_company_claim_precedence(claims: dict[str, str], expected: str | None) -> None:
    ids = {"C": uuid.uuid4(), "O": uuid.uuid4(), "X": uuid.uuid4()}
    payload = _claims(**{k: str(ids[v]) if v else v for k, v in claims.items()})
    user = user_from_claims(payload)
    assert user.company_id == (ids[expected] if expected else None)


def test_role_and_email_defaults() -> None:
    user = user_from_claims(_claims())
    assert user.role == "member"
    assert user.email == ""


def test_extra_claims_are_kept() -> None:
    user = user_from_claims(_claims(office_scope=["a", "b"], enabled_packs=["crm"]))
    assert user.claims["office_scope"] == ["a", "b"]
    assert user.claims["enabled_packs"] == ["crm"]


@pytest.mark.parametrize(
    ("role", "platform", "company"),
    [
        ("system_admin", True, True),
        ("platform_admin", True, False),  # a builder role, not a company admin
        ("company_admin", False, True),
        ("member", False, False),
        ("viewer", False, False),
    ],
)
def test_admin_rules(role: str, platform: bool, company: bool) -> None:
    user = user_from_claims(_claims(role=role))
    assert user.is_platform_admin is platform
    assert user.is_company_admin is company
