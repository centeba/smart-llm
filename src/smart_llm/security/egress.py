"""Outbound-egress URL validation (SSRF guard).

Tools that fetch a **model-controllable URL** (e.g. the ``scrape_url`` builtin)
can be steered by a prompt-injected model to hit internal services or the cloud
metadata endpoint (``169.254.169.254``). :func:`validate_egress_url` blocks any
URL whose host is — or resolves to — a loopback / private (RFC1918) / link-local
/ reserved address, and restricts schemes to http(s). An optional host allowlist
(arg or ``SMART_LLM_EGRESS_ALLOW_HOSTS``) permits explicitly-trusted internal
hosts.

Caveat: this is validate-then-connect, so a hostname could re-resolve to a
blocked IP after the check (DNS rebinding). It's defense-in-depth at the tool
boundary; a fetching worker should also pin the resolved IP / enforce egress.
"""

import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class EgressBlockedError(ValueError):
    """Raised when an outbound URL targets a disallowed scheme or address."""


def _env_allow_hosts() -> set[str]:
    raw = os.environ.get("SMART_LLM_EGRESS_ALLOW_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local  # 169.254.0.0/16 — includes the cloud metadata IP
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_egress_url(
    url: str,
    *,
    allow_hosts: set[str] | None = None,
    allow_schemes: tuple[str, ...] = ("http", "https"),
    resolve: bool = True,
) -> None:
    """Raise :class:`EgressBlockedError` if ``url`` is unsafe to fetch.

    Blocks non-http(s) schemes and any host that is (or, when ``resolve``,
    resolves to) a loopback / private / link-local / reserved address. Hosts in
    ``allow_hosts`` or ``SMART_LLM_EGRESS_ALLOW_HOSTS`` bypass the IP checks.
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in allow_schemes:
        raise EgressBlockedError(f"scheme {scheme or '(none)'!r} not allowed")
    host = parsed.hostname
    if not host:
        raise EgressBlockedError("URL has no host")

    allow = {h.lower() for h in (allow_hosts or set())} | _env_allow_hosts()
    if host.lower() in allow:
        return  # explicitly trusted internal host

    # Host given as an IP literal — check it directly (no DNS).
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_blocked_ip(literal):
            raise EgressBlockedError(f"host IP {host} is in a blocked range")
        return

    if not resolve:
        return

    port = parsed.port or (443 if scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise EgressBlockedError(f"cannot resolve host {host!r}: {exc}") from exc
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise EgressBlockedError(f"host {host} resolves to blocked address {addr}")


__all__ = ["EgressBlockedError", "validate_egress_url"]
