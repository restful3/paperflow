"""SSRF defense for papers._is_safe_public_host.

Covers:
- scheme allowlist (http/https only)
- hostname pattern denylist (localhost, .local, single-label, IPv6 loopback names)
- IP literal rejection (loopback, RFC1918, link-local, metadata, unspecified)
- DNS-resolved private IP rejection (hostname → private IP)
- IPv4-mapped IPv6 rejection (::ffff:127.0.0.1 style)
- malformed input rejection

Uses a monkeypatched socket.getaddrinfo so behavior is deterministic
without real DNS dependencies.
"""
import ipaddress
import socket

import pytest


# ── Deterministic DNS fixture ────────────────────────────────────────────────


_FAKE_DNS = {
    # Public hosts — should pass
    "example.com": "93.184.216.34",
    "arxiv.org": "151.101.0.42",
    "en.wikipedia.org": "208.80.154.224",
    # Hostname pointing to private IP — DNS-rebinding-shape attack vector
    "rebind-private.example": "192.168.1.50",
    # Hostname pointing to cloud metadata IP
    "metadata-attacker.example": "169.254.169.254",
    # Hostname pointing to IPv6 loopback
    "ipv6-loop.example": "::1",
}


def _fake_getaddrinfo(host, port, *args, **kwargs):
    """Echo IP literals; map known hostnames; raise gaierror for the rest."""
    # IP literal? Echo straight back as one record.
    stripped = host.strip("[]")
    try:
        ip_obj = ipaddress.ip_address(stripped)
        family = socket.AF_INET6 if isinstance(ip_obj, ipaddress.IPv6Address) else socket.AF_INET
        sockaddr = (stripped, port or 0, 0, 0) if family == socket.AF_INET6 else (stripped, port or 0)
        return [(family, socket.SOCK_STREAM, 0, "", sockaddr)]
    except ValueError:
        pass

    if host in _FAKE_DNS:
        ip = _FAKE_DNS[host]
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        sockaddr = (ip, port or 0, 0, 0) if family == socket.AF_INET6 else (ip, port or 0)
        return [(family, socket.SOCK_STREAM, 0, "", sockaddr)]

    raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")


@pytest.fixture
def mock_dns(monkeypatch):
    monkeypatch.setattr(
        "app.services.papers.socket.getaddrinfo",
        _fake_getaddrinfo,
        raising=True,
    )


# ── Allow: public URLs ───────────────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "https://example.com/paper.pdf",
    "https://arxiv.org/pdf/2401.12345",
    "http://en.wikipedia.org/wiki/Topic",
    "https://example.com:8443/secure-paper.pdf",
])
def test_public_urls_allowed(mock_dns, url):
    from app.services.papers import _is_safe_public_host
    ok, reason = _is_safe_public_host(url)
    assert ok, f"expected allowed but got reason={reason!r} for {url}"


# ── Block: non-http(s) schemes ───────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "ftp://example.com/file",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "data:text/html,foo",
    "gopher://example.com/",
])
def test_nonhttp_schemes_blocked(mock_dns, url):
    from app.services.papers import _is_safe_public_host
    ok, reason = _is_safe_public_host(url)
    assert not ok, f"expected blocked but got ok for {url}"
    assert "scheme" in reason.lower() or "http" in reason.lower()


# ── Block: obviously local hostnames (no DNS lookup needed) ──────────────────


@pytest.mark.parametrize("url", [
    "http://localhost/foo",
    "http://localhost:8090/api",
    "https://myhost.local/x",
    "http://app/internal",                # bare single-label
    "http://ip6-localhost/",
    "http://ip6-loopback/",
])
def test_local_hostnames_blocked(mock_dns, url):
    from app.services.papers import _is_safe_public_host
    ok, reason = _is_safe_public_host(url)
    assert not ok, f"expected blocked but got ok for {url}"


# ── Block: IP literals in the URL ────────────────────────────────────────────


@pytest.mark.parametrize("url,note", [
    ("http://127.0.0.1/",                              "IPv4 loopback"),
    ("http://127.5.5.5:8000/",                         "IPv4 loopback range"),
    ("http://10.0.0.1/",                               "RFC1918 10/8"),
    ("http://172.16.5.5/",                             "RFC1918 172.16/12"),
    ("http://192.168.1.1/",                            "RFC1918 192.168/16"),
    ("http://169.254.169.254/latest/meta-data/",       "AWS/GCE metadata"),
    ("http://169.254.1.1/",                            "IPv4 link-local"),
    ("http://0.0.0.0/",                                "IPv4 unspecified"),
    ("http://[::1]/",                                  "IPv6 loopback"),
    ("http://[fe80::1]/",                              "IPv6 link-local"),
    ("http://[fc00::1]/",                              "IPv6 unique-local"),
    ("http://[::]/",                                   "IPv6 unspecified"),
])
def test_ip_literals_blocked(mock_dns, url, note):
    from app.services.papers import _is_safe_public_host
    ok, reason = _is_safe_public_host(url)
    assert not ok, f"expected blocked ({note}) but got ok for {url}"


# ── Block: IPv4-mapped IPv6 wrapping a private address ───────────────────────


@pytest.mark.parametrize("url,note", [
    ("http://[::ffff:127.0.0.1]/",   "IPv4-mapped loopback"),
    ("http://[::ffff:10.0.0.1]/",    "IPv4-mapped RFC1918"),
    ("http://[::ffff:a9fe:a9fe]/",   "IPv4-mapped metadata 169.254.169.254"),
])
def test_ipv4_mapped_ipv6_unwraps_and_blocks(mock_dns, url, note):
    from app.services.papers import _is_safe_public_host
    ok, reason = _is_safe_public_host(url)
    assert not ok, f"expected blocked ({note}) but got ok for {url}"


# ── Block: hostname that resolves to a private IP (DNS-rebinding-shape) ──────


def test_hostname_resolving_to_private_ip_blocked(mock_dns):
    from app.services.papers import _is_safe_public_host
    ok, reason = _is_safe_public_host("https://rebind-private.example/foo")
    assert not ok
    # The reason should mention the resolved IP so operators can debug
    assert "192.168.1.50" in reason


def test_hostname_resolving_to_metadata_ip_blocked(mock_dns):
    from app.services.papers import _is_safe_public_host
    ok, reason = _is_safe_public_host("https://metadata-attacker.example/")
    assert not ok
    assert "169.254.169.254" in reason


def test_hostname_resolving_to_ipv6_loopback_blocked(mock_dns):
    from app.services.papers import _is_safe_public_host
    ok, reason = _is_safe_public_host("https://ipv6-loop.example/")
    assert not ok
    assert "::1" in reason


# ── Block: malformed / unresolvable input ────────────────────────────────────


def test_empty_url_blocked(mock_dns):
    from app.services.papers import _is_safe_public_host
    ok, reason = _is_safe_public_host("")
    assert not ok


def test_url_without_host_blocked(mock_dns):
    from app.services.papers import _is_safe_public_host
    ok, reason = _is_safe_public_host("http:///nopath")
    assert not ok


def test_unresolvable_hostname_blocked(mock_dns):
    from app.services.papers import _is_safe_public_host
    ok, reason = _is_safe_public_host("https://this-host-does-not-resolve.example/")
    assert not ok
    # Should communicate the DNS failure so operators don't think the URL is OK
    assert "resolve" in reason.lower() or "name" in reason.lower()
