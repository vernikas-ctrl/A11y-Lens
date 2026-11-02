"""Load a page in a real browser and ask axe-core what is wrong with it.

Phase 4. This module does the scanning and nothing else: it does not decide
whether a URL is allowed to be fetched. That check lives in `app.url_safety`
and is applied by the endpoint in task 4.7.

The split looks wrong at first glance -- surely the thing that fetches should
refuse to fetch dangerous addresses? -- so, the reasoning: `check_url` refuses
`file://` and refuses private addresses, both correctly. The test fixture is a
local HTML file. A scanner that policed its own input could therefore never be
tested against a page we control, and the tests would have to point at a real
website that can change without warning. Keeping the check at the front door
means it is enforced once, on everything that comes from outside, and the
scanner stays testable. `tests/test_scan_endpoint.py` asserts the check really
is applied there.

**Why a real browser.** Many sites build their content with JavaScript. Fetching
the HTML and parsing it would see an empty shell, report no problems, and be
wrong in the most reassuring possible way.

**Why async.** Playwright has a synchronous API that cannot be called from
inside a running event loop, which is what FastAPI is. Task 4.6 reuses one
browser across requests, so the browser has to live in the server's own loop.
Writing it synchronously now would mean rewriting it then.
"""

import re
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlsplit, urlunsplit

# Pinned deliberately, and vendored rather than fetched from a CDN -- see
# vendor/axe-core/README.md. Both must be changed together.
AXE_VERSION = "4.14.0"
AXE_SCRIPT_PATH = Path(__file__).parent / "vendor" / "axe-core" / "axe.min.js"

# axe's own defaults are used for *which* rules run, including its
# best-practice rules. That matches docs/api-contract.md, which says the `wcag`
# list "may be empty for best-practice rules with no WCAG mapping" -- so the
# contract already expects those results to be present.
#
# resultTypes trims what comes back: axe still evaluates everything, but only
# violations arrive with their full element detail. On a page like Wikipedia
# the passes list alone is thousands of nodes nobody reads.
AXE_RUN_OPTIONS: dict[str, Any] = {"resultTypes": ["violations"]}


def _axe_source() -> str:
    """The vendored axe-core, read from disk.

    Read on each call rather than cached at import: it costs a few milliseconds
    against a scan that takes seconds, and caching 650KB of JavaScript in the
    process of a 512MB-class server to save that is the wrong trade.
    """
    return AXE_SCRIPT_PATH.read_text(encoding="utf-8")


async def collect_violations(page) -> list[dict[str, Any]]:
    """Inject axe-core into an already-loaded page and run it.

    Takes a page rather than a URL so that the thing which drives the browser
    and the thing which drives axe can be tested apart from each other.

    Injected as `content` rather than from a URL: `add_script_tag(url=...)`
    would make the page itself fetch axe from the network, which is what
    vendoring it was meant to avoid.
    """
    await page.add_script_tag(content=_axe_source())
    result = await page.evaluate(
        "async (options) => await axe.run(document, options)",
        AXE_RUN_OPTIONS,
    )
    return result.get("violations", [])


# --- Task 4.3: axe's output, translated into our contract ------------------
#
# axe-core's shape and ours differ in three ways that matter:
#
# 1. **axe groups by rule, we list by element.** One `image-alt` violation
#    carrying four nodes is four issues in docs/api-contract.md, because the
#    UI shows one card per thing you have to go and fix.
# 2. **axe returns far more than we promised.** Tags for Section 508, EN
#    301 549, RGAA and its own categories; `failureSummary`; `relatedNodes`;
#    the raw check results. The contract lists the fields the frontend may
#    rely on, and anything extra would quietly become a field someone depends
#    on without it ever having been agreed.
# 3. **axe's WCAG references are tags, not numbers.** `wcag111` has to become
#    "1.1.1" before anyone can look it up.
#
# The contract is the source of truth for this shape, so it is deliberately
# *not* also declared as a pydantic model here -- two declarations of one
# shape drift apart. `tests/test_scanner.py` asserts the exact set of keys
# instead.

# The contract says `html` is "the offending element's outer HTML, truncated
# to 500 characters". A whole <table> would otherwise arrive in a response
# meant to be rendered in a code block.
MAX_HTML_LENGTH = 500

# axe severities, worst first. Also the order the UI groups by, and the key
# order of `summary`.
SEVERITIES = ("critical", "serious", "moderate", "minor")

# Used when axe reports no impact at all. "moderate" rather than "minor": an
# issue with an unknown severity should not be sorted to the bottom and
# ignored, and should not be shouted about either.
DEFAULT_SEVERITY = "moderate"

# A WCAG success-criterion tag: "wcag" followed by the digits of the criterion
# with the dots removed. Three or more digits, so the *level* tags are
# excluded -- `wcag2a`, `wcag21aa` and `wcag22aa` say which version and level
# a rule belongs to, not which criterion it tests.
WCAG_CRITERION_TAG = re.compile(r"^wcag(\d{3,})$")

# Playwright's own separator for "inside this frame, then this element". Only
# appears for a page with iframes; a normal page has one selector.
FRAME_SELECTOR_SEPARATOR = " >>> "


class Issue(TypedDict):
    """One thing to fix, exactly as docs/api-contract.md section 2.2 defines it."""

    id: str
    rule_id: str
    severity: str
    wcag: list[str]
    reference_url: str
    selector: str
    html: str
    explanation: None
    fix: None


def _wcag_criteria(tags: list[str]) -> list[str]:
    """Turn axe's tags into WCAG criterion numbers: wcag111 -> "1.1.1".

    The digits run together, so they have to be split by position: the first
    is the principle (1-4), the second the guideline, and whatever remains is
    the criterion -- which is why `wcag1410` is 1.4.10 and not 14.10.

    Returns an empty list for a best-practice rule with no WCAG mapping, which
    the contract explicitly allows. `heading-order` is one: a real problem,
    and not a WCAG failure on its own.
    """
    criteria = []
    for tag in tags:
        match = WCAG_CRITERION_TAG.match(tag)
        if match:
            digits = match.group(1)
            criteria.append(f"{digits[0]}.{digits[1]}.{digits[2:]}")
    return sorted(set(criteria))


def _reference_url(help_url: str) -> str:
    """Strip axe's telemetry parameter off the documentation link.

    axe appends `?application=axeAPI` to every helpUrl. It is meaningless to
    the reader, and this URL is shown to users.
    """
    parts = urlsplit(help_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _selector(target: Any) -> str:
    """Flatten axe's target into one selector string.

    `target` is a list, and for an element inside an iframe it is a list of
    lists: the path to the frame, then the path within it. Flattened and
    joined, because the contract promises a string.
    """
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(target)
    return FRAME_SELECTOR_SEPARATOR.join(parts)


def _truncate_html(html: str) -> str:
    """At most MAX_HTML_LENGTH characters, with a visible sign of the cut.

    The ellipsis replaces the last character rather than being added after it,
    so the result never exceeds the length the contract promised.
    """
    if len(html) <= MAX_HTML_LENGTH:
        return html
    return html[: MAX_HTML_LENGTH - 1] + "\u2026"


def normalise_violations(violations: list[dict[str, Any]]) -> list[Issue]:
    """axe-core's raw violations -> the contract's list of issues.

    Issues come back sorted worst-first, so the frontend does not have to
    decide what "worst" means and get a different answer from the backend.
    """
    issues: list[Issue] = []

    for violation in violations:
        rule_id = violation.get("id", "unknown")
        rule_impact = violation.get("impact")
        wcag = _wcag_criteria(violation.get("tags", []))
        reference_url = _reference_url(violation.get("helpUrl", ""))

        for index, node in enumerate(violation.get("nodes", [])):
            issues.append(
                Issue(
                    # Unique within this response only, and the contract says
                    # so: it is a UI key, not an identity that survives a
                    # rescan. Numbered per rule so it reads as
                    # "image-alt-0, image-alt-1".
                    id=f"{rule_id}-{index}",
                    rule_id=rule_id,
                    # The node's own impact where axe gives one: the same rule
                    # can be more serious on one element than another. Falls
                    # back to the rule's impact, then to a stated default.
                    severity=node.get("impact") or rule_impact or DEFAULT_SEVERITY,
                    wcag=wcag,
                    reference_url=reference_url,
                    selector=_selector(node.get("target", [])),
                    html=_truncate_html(node.get("html", "")),
                    # Filled in by Phase 5. The contract requires these two to
                    # be null together or populated together, never one alone.
                    explanation=None,
                    fix=None,
                )
            )

    issues.sort(key=lambda issue: _severity_rank(issue["severity"]))
    return issues


def _severity_rank(severity: str) -> int:
    """Worst first. Anything unrecognised sorts last rather than crashing."""
    try:
        return SEVERITIES.index(severity)
    except ValueError:
        return len(SEVERITIES)


def summarise(issues: list[Issue]) -> dict[str, int]:
    """Counts per severity, plus the total.

    Always all five keys, zeroes included -- contract rule 2. The UI reads
    `summary.critical` directly and must never have to check whether the key
    is there.
    """
    summary = {severity: 0 for severity in SEVERITIES}
    for issue in issues:
        if issue["severity"] in summary:
            summary[issue["severity"]] += 1
    summary["total"] = len(issues)
    return summary
