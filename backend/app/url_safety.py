"""Is this URL safe to fetch? Phase 3, run before anything loads a page.

The attack this exists to stop is SSRF -- Server-Side Request Forgery. This app
takes a URL from a stranger and makes *the server* visit it. Without a check,
someone enters `http://169.254.169.254/` (the address a cloud machine uses to
fetch its own credentials) or `http://10.0.0.5/` and the scanner obediently
loads it and shows them what it found. The server becomes a window into a
network they could not otherwise reach.

Two rules, in this order:

1. **The URL must be shaped like a web address** -- `http` or `https`, with a
   hostname. Allowed by allow-list, so `file://`, `javascript:`, `data:` and
   everything else nobody has thought of yet are refused by default.
2. **It must point somewhere public.** The hostname is *resolved* and every
   address it resolves to is checked. Pattern-matching the text cannot work:
   `localtest.me` is an ordinary public hostname that resolves to 127.0.0.1,
   and no list of forbidden strings catches it.

This module fetches nothing and knows nothing about Playwright. That makes the
rules testable without a browser or a network, which matters because these are
the tests that most need to be trustworthy.
"""

import ipaddress
import socket
from collections.abc import Callable, Sequence
from urllib.parse import urlsplit, urlunsplit

from app.errors import ApiError

# Browsers and servers vary, but nothing legitimate needs more than this, and
# an unbounded string is work handed to us by a caller.
MAX_URL_LENGTH = 2048

# An allow-list, deliberately. A block-list of dangerous schemes is a list you
# have to keep adding to, and the one you forget is the one that gets used.
ALLOWED_SCHEMES = frozenset({"http", "https"})

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# A hostname and a port, returning the addresses it resolves to. Injectable so
# tests can check the rules without depending on the internet or on what some
# domain happens to resolve to today.
Resolver = Callable[[str, int | None], Sequence[str]]


def resolve_hostname(hostname: str, port: int | None) -> Sequence[str]:
    """The real resolver: ask the operating system.

    SOCK_STREAM narrows the results to one entry per address rather than one
    per socket type, which only affects how many duplicates come back.
    """
    infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    # sockaddr is (host, port) for IPv4 and (host, port, flow, scope) for IPv6;
    # the address is first in both.
    return [str(info[4][0]) for info in infos]


def check_url(url: str, resolver: Resolver = resolve_hostname) -> str:
    """Return the URL, cleaned, or raise ApiError.

    Raises:
        ApiError("invalid_url"): not shaped like an http(s) web address.
        ApiError("blocked_address"): resolves somewhere private or reserved.
        ApiError("unreachable"): the hostname does not resolve at all.

    `unreachable` rather than `invalid_url` for a name that does not resolve is
    deliberate and comes from docs/api-contract.md: the address the user typed
    is fine, the site is the problem, and the message needs to say so.
    """
    parts = _check_shape(url)
    hostname = parts.hostname or ""
    _check_destination(hostname, parts.port, resolver)
    return urlunsplit(parts)


# --- Rule 1: shape --------------------------------------------------------


def _check_shape(url: str):
    """Reject anything that is not an http(s) address with a hostname."""
    if not isinstance(url, str) or not url.strip():
        raise ApiError("invalid_url", detail="No address was given.")

    url = url.strip()

    if len(url) > MAX_URL_LENGTH:
        raise ApiError(
            "invalid_url",
            detail=f"The address is longer than {MAX_URL_LENGTH} characters.",
        )

    try:
        parts = urlsplit(url)
        # Both of these parse lazily and raise only when read: an out-of-range
        # port, or a malformed IPv6 literal such as http://[::1 -- so they are
        # read here, inside the try, rather than wherever they are first used.
        hostname = parts.hostname
        _ = parts.port
    except ValueError as exc:
        raise ApiError("invalid_url", detail="That address could not be read.") from exc

    if parts.scheme not in ALLOWED_SCHEMES:
        raise ApiError(
            "invalid_url",
            detail="Only http:// and https:// addresses can be scanned.",
        )

    if not hostname:
        raise ApiError("invalid_url", detail="That address has no website name in it.")

    # http://expected.com@evil.com/ connects to evil.com, but a human reading it
    # sees expected.com. Refused rather than stripped: a URL carrying a username
    # is either an attempt to mislead or a mistake, and neither should be
    # silently repaired into something that then gets fetched.
    if parts.username is not None or parts.password is not None:
        raise ApiError(
            "invalid_url",
            detail="Addresses containing a username or password are not accepted.",
        )

    return parts


# --- Rule 2: where it really points ---------------------------------------

# Checked in order, so the reason given is the most specific true one. The last
# entry is the real safety net: `is_global` is the standard library's own
# judgement of "reachable on the public internet", and it catches ranges the
# other flags miss -- 100.64.0.0/10, the carrier-grade NAT range, is not
# `is_private` on this Python but is not global either.
#
# The reverse is also true, which is why `is_global` cannot be the only check:
# multicast 224.0.0.1 reports `is_global` as True.
_BLOCK_REASONS: tuple[tuple[str, Callable[[IpAddress], bool]], ...] = (
    ("the loopback address, meaning this server itself", lambda ip: ip.is_loopback),
    (
        "a link-local address, which includes the cloud metadata service",
        lambda ip: ip.is_link_local,
    ),
    ("a private network address", lambda ip: ip.is_private),
    ("a reserved address", lambda ip: ip.is_reserved),
    ("a multicast address", lambda ip: ip.is_multicast),
    ("an unspecified address", lambda ip: ip.is_unspecified),
    ("not a publicly reachable address", lambda ip: not ip.is_global),
)


def _unwrap(ip: IpAddress) -> IpAddress:
    """Pull the real IPv4 address out of an IPv6 address that is carrying one.

    `::ffff:127.0.0.1` is loopback wearing an IPv6 costume. Python already
    classifies that particular form correctly, but 6to4 and Teredo addresses
    embed an IPv4 address that the flags do not look inside, so all three are
    unwrapped here and judged on what they actually contain.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return ip.ipv4_mapped
        if ip.sixtofour:
            return ip.sixtofour
        if ip.teredo:
            # (server, client) -- the client is the address traffic reaches.
            return ip.teredo[1]
    return ip


def _blocked_reason(ip: IpAddress) -> str | None:
    """The reason this address may not be scanned, or None if it may be."""
    ip = _unwrap(ip)
    for reason, is_match in _BLOCK_REASONS:
        if is_match(ip):
            return reason
    return None


def _check_destination(hostname: str, port: int | None, resolver: Resolver) -> None:
    """Resolve the hostname and refuse if anything it points to is private."""
    literal = _as_ip_literal(hostname)
    if literal is not None:
        # An address typed directly. No DNS involved, so nothing to resolve.
        _reject_if_blocked(literal, hostname)
        return

    try:
        addresses = resolver(hostname, port)
    except OSError as exc:
        # DNS said no such name, or could not be asked. Per the contract this
        # is the site's problem, not a malformed request. `detail` stays
        # generic: a resolver error string can name internal DNS servers.
        raise ApiError("unreachable", detail="That website name could not be found.") from exc

    if not addresses:
        raise ApiError("unreachable", detail="That website name could not be found.")

    # Every address, not just the first. A hostname can answer with one public
    # and one private address, and checking addresses[0] would let the private
    # one through whenever the resolver happened to order it second.
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            # The resolver returned something that is not an address. Refuse
            # rather than ignore: an address we cannot classify is one we
            # cannot vouch for.
            raise ApiError(
                "blocked_address",
                detail="That address could not be checked, so it was not scanned.",
            ) from exc
        _reject_if_blocked(ip, hostname)


def _as_ip_literal(hostname: str) -> IpAddress | None:
    """The hostname as an IP address, if that is what it is."""
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        return None


def _reject_if_blocked(ip: IpAddress, hostname: str) -> None:
    reason = _blocked_reason(ip)
    if reason is None:
        return
    # Naming the address is intentional, and matches the example in
    # docs/api-contract.md. Someone scanning their own staging site needs to
    # know *why* it was refused, and the address is one they already own.
    #
    # Worded differently for a typed address, so it does not read as the
    # nonsense "169.254.169.254 resolves to 169.254.169.254".
    if hostname == str(ip):
        detail = f"{ip} is {reason}."
    else:
        detail = f"{hostname} resolves to {ip}, which is {reason}."
    raise ApiError("blocked_address", detail=detail)
