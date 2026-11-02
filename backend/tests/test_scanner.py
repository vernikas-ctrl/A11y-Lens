"""Tasks 4.2, 4.3 and 4.5 -- the scanner, and the shape of what it returns.

Two kinds of test here, deliberately separated:

- **Translation tests**, which feed hand-written axe output to the mapping
  functions. Instant, and they can describe situations the fixture page cannot
  produce on demand -- an element inside an iframe, a rule with no severity, a
  500-character element.
- **One real scan** of `fixtures/broken.html` in a real Chromium. That costs a
  few seconds, so it runs exactly once for the whole module and every test
  asserts against the result.

The real scan asserts on **rule ids, never on counts**, as TASKS.md insists:
an axe-core update that adds a rule would otherwise fail a count assertion
months later, with nothing to say why.

No `pytest-asyncio`. The browser work is async, but it is run once inside a
plain fixture with `asyncio.run()` and what comes back is ordinary data, so
every test here is an ordinary synchronous test. One dependency and a pile of
event-loop-scope configuration avoided for no loss.
"""

import asyncio
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from app.scanner import (
    DEFAULT_SEVERITY,
    MAX_HTML_LENGTH,
    SEVERITIES,
    _reference_url,
    _selector,
    _truncate_html,
    _wcag_criteria,
    collect_violations,
    normalise_violations,
    summarise,
)

FIXTURE = Path(__file__).parent / "fixtures" / "broken.html"

# Every fault planted in broken.html, and the axe rule each one should trigger.
# If a future axe-core renames or retires one of these, this is the list that
# fails and says so.
PLANTED_FAULTS = {
    "image-alt": "an image with no alt attribute",
    "label": "a form field with nothing naming it",
    "heading-order": "a heading level skipped, h2 straight to h4",
    "button-name": "a button containing only an icon",
    "color-contrast": "grey text on white, about 2.85:1",
    "html-has-lang": "no lang attribute on the page",
}


@pytest.fixture(scope="module")
def scanned() -> list[dict]:
    """Scan the local fixture once, and hand every test the normalised issues.

    Module-scoped because launching Chromium is the expensive part by a wide
    margin -- Phase 1 measured a scan at several hundred megabytes and several
    seconds, and that was the whole reason task 4.6 exists.

    Loaded over file:// , so this test needs no network and no web server. It
    is also why the scanner does not check its own URLs: app.url_safety would
    refuse file:// , correctly, and then this test could not exist.
    """

    async def run() -> list[dict]:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                page = await browser.new_page()
                await page.goto(FIXTURE.resolve().as_uri(), wait_until="load")
                violations = await collect_violations(page)
            finally:
                await browser.close()
        return normalise_violations(violations)

    return asyncio.run(run())


# --- The real scan ----------------------------------------------------------


def test_the_fixture_file_exists():
    """A missing fixture would otherwise show up as "no violations found",
    which looks like a scanner bug rather than a missing file."""
    assert FIXTURE.is_file()


@pytest.mark.parametrize("rule_id", sorted(PLANTED_FAULTS))
def test_each_planted_fault_is_found(scanned, rule_id):
    """Task 4.5's "Done when" asks for at least four specific rule ids. There
    are six, one per planted fault."""
    found = {issue["rule_id"] for issue in scanned}

    assert rule_id in found, (
        f"{rule_id} not reported, but broken.html contains "
        f"{PLANTED_FAULTS[rule_id]}. Found: {sorted(found)}"
    )


def test_the_correctly_built_elements_are_not_reported(scanned):
    """broken.html contains a properly labelled input, an image with real alt
    text and a button with a visible name. A scanner that flagged those would
    be useless even while passing every test above."""
    selectors = " ".join(issue["selector"] for issue in scanned)

    assert "#email-field" not in selectors
    assert "#postcode-field" not in selectors


def test_the_blind_spot_stays_unreported(scanned):
    """Documents a limitation rather than a feature.

    `#placeholder-only-field` is named only by its placeholder text, which
    disappears the moment someone types. axe-core treats a placeholder as a
    valid accessible name and passes the rule outright. It is right about the
    specification and wrong about the person.

    Asserted so that this stays a known, written-down gap: if a future
    axe-core starts catching it, this test fails and tells us, rather than the
    blind spot quietly closing without anyone noticing.
    """
    selectors = " ".join(issue["selector"] for issue in scanned)

    assert "#placeholder-only-field" not in selectors, (
        "axe now catches placeholder-only labelling -- good news. Update the "
        "BLIND SPOT comment in broken.html and the caveat in the README."
    )


def test_every_issue_matches_the_contract_exactly(scanned):
    """No leftover axe-specific fields, which is task 4.3's "Done when".

    axe returns failureSummary, relatedNodes, the raw check results and tags
    for four other standards. Anything extra that leaked through would become
    a field the frontend starts relying on without it ever being agreed.
    """
    expected_keys = {
        "id", "rule_id", "severity", "wcag", "reference_url",
        "selector", "html", "explanation", "fix",
    }

    assert scanned, "the fixture produced no issues at all"
    for issue in scanned:
        assert set(issue) == expected_keys, f"{issue['rule_id']} has wrong keys"
        assert issue["severity"] in SEVERITIES
        assert isinstance(issue["wcag"], list)
        assert len(issue["html"]) <= MAX_HTML_LENGTH
        # Contract rule 4: null together or populated together. Phase 5 fills
        # both; until then both must be absent.
        assert issue["explanation"] is None
        assert issue["fix"] is None


def test_issues_come_back_worst_first(scanned):
    """Sorted in the backend so the backend and the frontend cannot disagree
    about what "worst" means."""
    ranks = [SEVERITIES.index(issue["severity"]) for issue in scanned]

    assert ranks == sorted(ranks)


def test_a_wcag_rule_carries_its_criterion(scanned):
    image_alt = next(i for i in scanned if i["rule_id"] == "image-alt")

    assert image_alt["wcag"] == ["1.1.1"]
    assert image_alt["reference_url"].startswith("https://dequeuniversity.com/")
    assert "?" not in image_alt["reference_url"]


def test_a_best_practice_rule_carries_no_criterion(scanned):
    """`heading-order` is a real problem and not a WCAG failure on its own, so
    its `wcag` list is empty -- which the contract explicitly allows, and which
    the UI must therefore cope with."""
    heading_order = next(i for i in scanned if i["rule_id"] == "heading-order")

    assert heading_order["wcag"] == []


def test_the_summary_describes_the_scan(scanned):
    summary = summarise(scanned)

    assert set(summary) == {"critical", "serious", "moderate", "minor", "total"}
    assert summary["total"] == len(scanned)
    assert sum(summary[s] for s in SEVERITIES) == summary["total"]
    assert summary["critical"] >= 1, "image-alt and button-name are both critical"


# --- Translating axe's output -----------------------------------------------


@pytest.mark.parametrize(
    "tags,expected",
    [
        pytest.param(["wcag2a", "wcag111"], ["1.1.1"], id="level-tag-dropped"),
        pytest.param(["wcag2aa", "wcag143"], ["1.4.3"], id="contrast"),
        pytest.param(["wcag412"], ["4.1.2"], id="name-role-value"),
        pytest.param(["wcag1410"], ["1.4.10"], id="two-digit-criterion"),
        pytest.param(["wcag2410"], ["2.4.10"], id="two-digit-criterion-elsewhere"),
        pytest.param(["cat.aria", "best-practice"], [], id="best-practice-only"),
        pytest.param(["wcag21aa", "wcag22aa"], [], id="version-and-level-tags"),
        pytest.param([], [], id="no-tags"),
        pytest.param(["wcag111", "wcag111"], ["1.1.1"], id="deduplicated"),
        pytest.param(["wcag412", "wcag111"], ["1.1.1", "4.1.2"], id="sorted"),
    ],
)
def test_wcag_tags_become_criterion_numbers(tags, expected):
    """`wcag1410` is 1.4.10, not 14.10. The digits run together, so they have
    to be split by position -- principle, guideline, then the rest."""
    assert _wcag_criteria(tags) == expected


def test_the_reference_url_loses_axes_telemetry_parameter():
    assert _reference_url(
        "https://dequeuniversity.com/rules/axe/4.14/image-alt?application=axeAPI"
    ) == "https://dequeuniversity.com/rules/axe/4.14/image-alt"


@pytest.mark.parametrize(
    "target,expected",
    [
        pytest.param(["img:nth-child(2)"], "img:nth-child(2)", id="ordinary-page"),
        pytest.param(
            [["#frame"], ["button"]], "#frame >>> button", id="inside-an-iframe"
        ),
        pytest.param([], "", id="nothing"),
    ],
)
def test_the_selector_is_flattened_into_one_string(target, expected):
    """The contract promises a string; axe gives a list, and a list of lists
    once an iframe is involved."""
    assert _selector(target) == expected


def test_long_html_is_cut_to_the_promised_length():
    cut = _truncate_html("<div>" + "x" * 900 + "</div>")

    assert len(cut) == MAX_HTML_LENGTH
    assert cut.endswith("…")


def test_short_html_is_left_alone():
    assert _truncate_html("<img src='a.png'>") == "<img src='a.png'>"


def test_html_exactly_at_the_limit_is_not_cut():
    """The off-by-one worth having a test for."""
    exact = "x" * MAX_HTML_LENGTH

    assert _truncate_html(exact) == exact


def test_one_rule_with_several_elements_becomes_several_issues():
    """axe groups by rule; the contract lists by element, because the UI shows
    one card per thing you have to go and fix."""
    issues = normalise_violations(
        [
            {
                "id": "image-alt",
                "impact": "critical",
                "tags": ["wcag111"],
                "helpUrl": "https://example.com/image-alt?application=axeAPI",
                "nodes": [
                    {"target": ["img:nth-child(1)"], "html": "<img src='a'>"},
                    {"target": ["img:nth-child(2)"], "html": "<img src='b'>"},
                    {"target": ["img:nth-child(3)"], "html": "<img src='c'>"},
                ],
            }
        ]
    )

    assert [issue["id"] for issue in issues] == [
        "image-alt-0",
        "image-alt-1",
        "image-alt-2",
    ]
    assert {issue["rule_id"] for issue in issues} == {"image-alt"}
    assert {issue["severity"] for issue in issues} == {"critical"}


def test_a_node_overrides_the_rules_severity():
    """The same rule can be worse on one element than another, and axe says so
    per node. The contract's severity is per issue, so the node wins."""
    issues = normalise_violations(
        [
            {
                "id": "color-contrast",
                "impact": "serious",
                "tags": [],
                "helpUrl": "",
                "nodes": [
                    {"target": ["p"], "html": "<p>a</p>", "impact": "minor"},
                    {"target": ["h2"], "html": "<h2>b</h2>"},
                ],
            }
        ]
    )
    by_selector = {issue["selector"]: issue["severity"] for issue in issues}

    assert by_selector == {"p": "minor", "h2": "serious"}


def test_a_missing_severity_falls_back_rather_than_crashing():
    """axe can report no impact at all. The fallback is stated rather than
    accidental, and it is not `minor`: an unknown severity should not be
    sorted to the bottom and ignored."""
    issues = normalise_violations(
        [{"id": "odd-rule", "tags": [], "helpUrl": "", "nodes": [{"target": ["p"]}]}]
    )

    assert issues[0]["severity"] == DEFAULT_SEVERITY
    assert issues[0]["html"] == ""


def test_no_violations_is_a_valid_result():
    """Contract rule 3: empty is a successful scan, not a failure."""
    assert normalise_violations([]) == []
    assert summarise([]) == {
        "critical": 0,
        "serious": 0,
        "moderate": 0,
        "minor": 0,
        "total": 0,
    }
