"""Task 3.3 -- the SSRF rules.

The suite you will be gladdest to have. Every case below is a URL someone could
type into the app, and the assertion is what the server must do about it.

Two deliberate choices:

- **The hostname cases use a stubbed resolver.** A test that depends on what
  `example.com` resolves to today is a test that fails one morning for reasons
  that have nothing to do with the code. The stub also lets us construct the
  cases that matter most and cannot be arranged otherwise -- a public hostname
  pointing at 127.0.0.1, or one answering with a public *and* a private
  address.
- **The literal-IP cases use no resolver at all**, because an address typed
  directly needs no DNS. `localhost` is the one hostname resolved for real: it
  comes from the machine's own hosts file, needs no network, and the task's
  "Done when" names it specifically.
"""

import socket

import pytest

from app.errors import ApiError
from app.url_safety import MAX_URL_LENGTH, check_url


def refuse(url: str, resolver=None) -> ApiError:
    """Run the check and return the error it raised."""
    with pytest.raises(ApiError) as caught:
        check_url(url, **({"resolver": resolver} if resolver else {}))
    return caught.value


def resolving_to(*addresses: str):
    """A resolver that always answers with these addresses."""
    return lambda hostname, port: list(addresses)


# --- 3.1 The URL must be shaped like a web address --------------------------

BAD_SHAPE = [
    pytest.param("", id="empty"),
    pytest.param("   ", id="whitespace-only"),
    pytest.param("not a url", id="prose"),
    pytest.param("example.com", id="no-scheme"),
    pytest.param("//example.com", id="protocol-relative"),
    pytest.param("file:///etc/passwd", id="file-scheme"),
    pytest.param("javascript:alert(1)", id="javascript-scheme"),
    pytest.param("data:text/html,<h1>hi</h1>", id="data-scheme"),
    pytest.param("ftp://example.com/x", id="ftp-scheme"),
    pytest.param("http://", id="scheme-only"),
    pytest.param("http://:8000/", id="port-but-no-host"),
    pytest.param("http://example.com:99999/", id="port-out-of-range"),
    pytest.param("http://[::1/", id="malformed-ipv6-literal"),
    pytest.param("https://" + "a" * MAX_URL_LENGTH, id="too-long"),
]


@pytest.mark.parametrize("url", BAD_SHAPE)
def test_badly_shaped_urls_are_invalid(url):
    """The task's stated "Done when" for 3.1.

    None of these reaches DNS, so no resolver is needed -- and passing one
    would hide a bug where the shape check is skipped.
    """
    error = refuse(url)

    assert error.code == "invalid_url"
    assert error.status_code == 400


CREDENTIALS_IN_URL = [
    pytest.param("https://user:pass@example.com/", id="username-and-password"),
    pytest.param("https://user@example.com/", id="username-only"),
    pytest.param("http://expected.com@evil.example/", id="the-misleading-one"),
]


@pytest.mark.parametrize("url", CREDENTIALS_IN_URL)
def test_credentials_in_the_url_are_refused(url):
    """`http://expected.com@evil.example/` connects to evil.example, while a
    human reading it sees expected.com. Refused outright rather than stripped:
    repairing it would mean fetching something the user did not read."""
    error = refuse(url, resolver=resolving_to("93.184.216.34"))

    assert error.code == "invalid_url"
    assert "username" in (error.detail or "")


# --- 3.2 It must point somewhere public -------------------------------------

BLOCKED_LITERALS = [
    pytest.param("http://127.0.0.1/", id="loopback"),
    pytest.param("http://127.0.0.1:8080/admin", id="loopback-other-port"),
    pytest.param("http://127.1.2.3/", id="loopback-whole-127-range"),
    pytest.param("http://[::1]/", id="loopback-ipv6"),
    pytest.param("http://[::ffff:127.0.0.1]/", id="loopback-ipv4-mapped-ipv6"),
    pytest.param("http://169.254.169.254/", id="cloud-metadata"),
    pytest.param("http://169.254.169.254/latest/meta-data/iam/", id="metadata-creds"),
    pytest.param("http://10.0.0.1/", id="private-10"),
    pytest.param("http://192.168.1.1/", id="private-192-168"),
    pytest.param("http://172.16.0.1/", id="private-172-16-low-edge"),
    pytest.param("http://172.31.255.254/", id="private-172-31-high-edge"),
    pytest.param("http://[fc00::1]/", id="private-ipv6-unique-local"),
    pytest.param("http://[fe80::1]/", id="link-local-ipv6"),
    pytest.param("http://0.0.0.0/", id="unspecified"),
    pytest.param("http://[::]/", id="unspecified-ipv6"),
    pytest.param("http://100.64.0.1/", id="carrier-grade-nat"),
    pytest.param("http://224.0.0.1/", id="multicast"),
    pytest.param("http://240.0.0.1/", id="reserved"),
    pytest.param("http://192.0.2.1/", id="documentation-range"),
]


@pytest.mark.parametrize("url", BLOCKED_LITERALS)
def test_addresses_inside_the_network_are_blocked(url):
    """Covers 3.2's "Done when" for the two literal addresses it names, plus
    the ranges either flag on its own would miss.

    `100.64.0.1` is the carrier-grade NAT range: Python does not call it
    private, only not-globally-reachable. `224.0.0.1` is the reverse -- it
    reports as globally reachable, and is caught by the multicast check. Each
    check is here because the other one lets one of these through.
    """
    error = refuse(url)

    assert error.code == "blocked_address"
    assert error.status_code == 400


def test_localhost_is_blocked():
    """3.2's "Done when" names this URL exactly. `localhost` is a hostname, so
    it goes through real resolution -- which reads the machine's own hosts file
    and needs no network."""
    error = refuse("http://localhost:8000/health")

    assert error.code == "blocked_address"


def test_a_public_hostname_pointing_at_loopback_is_blocked():
    """The reason this check resolves instead of pattern-matching text.

    `localtest.me` is a real, public, perfectly ordinary domain name whose A
    record is 127.0.0.1. No list of forbidden strings catches it; resolving it
    catches it immediately.
    """
    error = refuse("http://localtest.me/", resolver=resolving_to("127.0.0.1"))

    assert error.code == "blocked_address"
    assert "127.0.0.1" in (error.detail or "")


def test_every_resolved_address_is_checked_not_just_the_first():
    """A hostname can answer with several addresses. If only the first were
    checked, this URL would be allowed or refused depending on the order the
    resolver happened to return them in -- which is not under our control and
    can differ between two calls."""
    error = refuse(
        "http://mixed.example/",
        resolver=resolving_to("93.184.216.34", "10.0.0.5"),
    )

    assert error.code == "blocked_address"
    assert "10.0.0.5" in (error.detail or "")


def test_the_reason_names_the_address_and_why():
    """`detail` has to be useful: someone scanning their own staging site needs
    to know why it was refused. The address is one they already own."""
    error = refuse("http://169.254.169.254/")

    assert "169.254.169.254" in (error.detail or "")
    assert "metadata" in (error.detail or "")


def test_an_unclassifiable_resolver_answer_is_refused_not_ignored():
    """An address we cannot parse is an address we cannot vouch for."""
    error = refuse("http://odd.example/", resolver=resolving_to("not-an-address"))

    assert error.code == "blocked_address"


# --- Public addresses must still work ---------------------------------------

ALLOWED = [
    pytest.param("https://example.com/", "93.184.216.34", id="plain-https"),
    pytest.param("http://example.com/", "93.184.216.34", id="plain-http"),
    pytest.param("https://sub.domain.co.uk/a/b?q=1#frag", "8.8.8.8", id="deep-path"),
    pytest.param("http://example.com:8080/", "8.8.8.8", id="non-standard-port"),
    pytest.param("https://EXAMPLE.com/", "93.184.216.34", id="uppercase-host"),
]


@pytest.mark.parametrize("url,address", ALLOWED)
def test_public_addresses_are_allowed(url, address):
    """A non-standard port is allowed on purpose: the IP check is what provides
    the safety, and restricting ports to 80 and 443 would only break real sites
    on :8080 without closing anything the IP check leaves open."""
    assert check_url(url, resolver=resolving_to(address))


ALLOWED_LITERALS = [
    pytest.param("http://8.8.8.8/", id="public-ipv4-literal"),
    pytest.param("http://[2606:4700::1111]/", id="public-ipv6-literal"),
    pytest.param("http://172.32.0.1/", id="just-above-the-private-172-range"),
    pytest.param("http://172.15.255.255/", id="just-below-the-private-172-range"),
]


@pytest.mark.parametrize("url", ALLOWED_LITERALS)
def test_public_literal_addresses_are_allowed(url):
    """The two 172.x cases are the boundary of 172.16.0.0/12 -- the range most
    often written out by hand and most often written out wrong. They are here
    so the check is known to block the range and not the whole of 172."""
    assert check_url(url)


def test_the_cleaned_url_comes_back():
    """The caller fetches what check_url returns, not what it was given, so the
    two must describe the same page."""
    assert check_url(
        "  https://example.com/path?q=1  ", resolver=resolving_to("93.184.216.34")
    ) == "https://example.com/path?q=1"


# --- A name that does not resolve is the site's problem ---------------------


def test_a_name_that_does_not_resolve_is_unreachable_not_invalid():
    """Per docs/api-contract.md, `unreachable` (502) rather than
    `invalid_url`: the address the user typed is fine, the site is the problem,
    and the message they see needs to say that."""

    def failing_resolver(hostname, port):
        raise socket.gaierror("Name or service not known")

    error = refuse("https://this-domain-does-not-exist-9z8y.com/", failing_resolver)

    assert error.code == "unreachable"
    assert error.status_code == 502


def test_a_resolver_answering_with_nothing_is_unreachable():
    """Defensive: an empty answer must not fall through the per-address loop
    and be treated as having passed every check."""
    assert refuse("https://silent.example/", resolving_to()).code == "unreachable"


def test_the_unreachable_detail_does_not_echo_the_resolver_error():
    """A resolver error string can name internal DNS servers, and this response
    goes to a stranger."""

    def leaky_resolver(hostname, port):
        raise socket.gaierror("lookup failed via ns1.internal.corp 10.0.0.53")

    detail = refuse("https://x.example/", leaky_resolver).detail or ""

    assert "internal.corp" not in detail
    assert "10.0.0.53" not in detail
