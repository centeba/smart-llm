"""SSRF egress guard — block internal/metadata/private targets; allowlist bypass."""

import pytest

from smart_llm.security.egress import EgressBlockedError, validate_egress_url


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://127.0.0.1:8000/admin",  # loopback
        "http://10.0.0.5/internal",  # RFC1918
        "http://192.168.1.1/",  # RFC1918
        "http://[::1]/",  # IPv6 loopback
        "http://0.0.0.0/",  # unspecified
    ],
)
def test_blocks_internal_ip_literals(url):
    with pytest.raises(EgressBlockedError):
        validate_egress_url(url)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/x", "gopher://h/"])
def test_blocks_non_http_schemes(url):
    with pytest.raises(EgressBlockedError):
        validate_egress_url(url)


def test_blocks_missing_host():
    with pytest.raises(EgressBlockedError):
        validate_egress_url("http:///nohost")


def test_localhost_resolution_blocked():
    # 'localhost' resolves (offline, via the hosts file) to loopback → blocked.
    with pytest.raises(EgressBlockedError):
        validate_egress_url("http://localhost:9000/")


def test_allowlist_arg_bypasses_ip_check():
    # An explicitly trusted internal host is permitted without IP inspection.
    validate_egress_url("http://mit-stack-api:8000/x", allow_hosts={"mit-stack-api"})


def test_allowlist_env_bypasses(monkeypatch):
    monkeypatch.setenv("SMART_LLM_EGRESS_ALLOW_HOSTS", "internal-svc, other")
    validate_egress_url("http://internal-svc/x")


def test_public_host_allowed(monkeypatch):
    # Avoid real DNS: pretend the host resolves to a public IP.
    import smart_llm.security.egress as mod

    monkeypatch.setattr(
        mod.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 80))],
    )
    validate_egress_url("http://example.com/page")  # no raise


def test_public_hostname_resolving_to_private_blocked(monkeypatch):
    import smart_llm.security.egress as mod

    # A public-looking name that resolves to a private IP (DNS-rebinding style).
    monkeypatch.setattr(
        mod.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("10.1.2.3", 80))],
    )
    with pytest.raises(EgressBlockedError):
        validate_egress_url("http://sneaky.example.com/")


@pytest.mark.asyncio
async def test_scraper_blocks_metadata_url_without_fetching():
    from smart_llm.builtins.scraper import ScrapeUrlArgs, ScrapeUrlSkill

    tool = ScrapeUrlSkill()
    args = ScrapeUrlArgs(url="http://169.254.169.254/latest/meta-data/iam/")
    result = await tool.run_action(args, db_session=None)
    assert "egress blocked" in result.get("error", "")
