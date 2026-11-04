"""Task 10.5 — the frontend's request budget must cover this backend.

Why this test is in the backend's suite
---------------------------------------
A scan is slow, and both halves of the app have an opinion about how slow is
too slow. They used to disagree. The frontend gave up after 90 seconds; this
backend can legitimately take 120, because it spends ``SCAN_TIMEOUT_MS``
twice in series — once navigating to the page, then again as a separate budget
for the axe run — and ``EXPLAIN_TIMEOUT_MS`` after both. The result was a bug
with no stack trace: a slow page that was about to succeed got reported to the
person as a timeout, while this process still had thirty seconds of budget
left and a finished report on the way.

Fixing the arithmetic once does not stop it recurring. Both numbers are
environment variables on the deploy host, changeable by somebody who has never
opened ``frontend/src/config.ts``. So the files are read as text and compared
here, which makes drift a failing test rather than an intermittent complaint
from a user.

It lives here rather than in the frontend's suite because the frontend
deliberately has no filesystem types — ``frontend/src/palette.test.ts``
explains that choice — while Python reads a ``.ts`` file as text without
asking anybody's permission.

What is *not* checked here: the frontend's own behaviour when the override is
set, which is ``frontend/src/config.test.ts``'s job.
"""

import re
from pathlib import Path

import pytest

from app.config import Settings

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent

ENV_EXAMPLE = BACKEND / ".env.example"
SCANNER = BACKEND / "app" / "scanner.py"
FRONTEND_CONFIG = REPO / "frontend" / "src" / "config.ts"

# How many times a scan spends its page-load budget, one after another: the
# navigation, then the axe run. The frontend holds the same number under the
# name SCAN_BUDGETS_SPENT, and a test below checks it still matches.
BUDGETS_SPENT = 2


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def env_value(name: str) -> int:
    """The number in `NAME=12345`, out of .env.example."""
    match = re.search(rf"^{name}=(\d+)\s*$", read(ENV_EXAMPLE), re.MULTILINE)
    assert match is not None, f"{name} is not set to a whole number in .env.example"
    return int(match.group(1))


def ts_constant(name: str) -> int:
    """The number in `const NAME = 30_000`, out of the frontend's config.

    Read as text rather than executed. Running a TypeScript file from pytest
    would mean a Node toolchain in the backend's test dependencies, to learn
    something a line of text already says.
    """
    match = re.search(rf"const {name} = ([\d_]+)", read(FRONTEND_CONFIG))
    assert match is not None, f"{name} is not declared in frontend/src/config.ts"
    return int(match.group(1).replace("_", ""))


class TestTheCeilingsAgree:
    """The same numbers, in two languages, with nothing to keep them together."""

    def test_env_example_matches_the_compiled_defaults(self):
        # .env.example is documentation; the Field defaults are what actually
        # runs when a variable is unset. A deploy that forgets one gets the
        # other, so they have to say the same thing.
        defaults = Settings.model_fields
        assert env_value("SCAN_TIMEOUT_MS") == defaults["scan_timeout_ms"].default
        assert env_value("EXPLAIN_TIMEOUT_MS") == defaults["explain_timeout_ms"].default

    def test_frontend_knows_this_backends_page_ceiling(self):
        assert ts_constant("BACKEND_SCAN_TIMEOUT_MS") == env_value("SCAN_TIMEOUT_MS")

    def test_frontend_knows_this_backends_explanation_ceiling(self):
        assert ts_constant("BACKEND_EXPLAIN_TIMEOUT_MS") == env_value(
            "EXPLAIN_TIMEOUT_MS"
        )

    def test_frontend_counts_the_page_budget_as_often_as_we_spend_it(self):
        assert ts_constant("SCAN_BUDGETS_SPENT") == BUDGETS_SPENT

    def test_the_frontend_waits_longer_than_our_worst_case(self):
        our_worst_case = BUDGETS_SPENT * env_value("SCAN_TIMEOUT_MS") + env_value(
            "EXPLAIN_TIMEOUT_MS"
        )

        # The default the frontend arrives at, worked out from its own three
        # constants exactly as `readTimeout` does.
        their_budget = (
            ts_constant("SCAN_BUDGETS_SPENT") * ts_constant("BACKEND_SCAN_TIMEOUT_MS")
            + ts_constant("BACKEND_EXPLAIN_TIMEOUT_MS")
            + ts_constant("COLD_START_ALLOWANCE_MS")
        )

        # Strictly longer, not equal. Equal would be no better than the bug
        # this file exists for: our last millisecond of budget is spent before
        # Chromium has even been launched, never mind the network.
        assert their_budget > our_worst_case


class TestWeStillSpendItWhereWeSayWeDo:
    """BUDGETS_SPENT is the number that made the old timeout wrong.

    A third place would make the worst case 150 seconds and the frontend's
    budget wrong again, silently. If one of these fails, the fix is to correct
    BUDGETS_SPENT here and SCAN_BUDGETS_SPENT in the frontend — not to loosen
    the test.
    """

    @pytest.mark.parametrize(
        "site, what_it_is",
        [
            ("timeout=timeout_ms", "the navigation in _goto"),
            ("asyncio.timeout(timeout_ms", "the axe run in scan"),
        ],
    )
    def test_the_known_budget_sites_are_still_there(self, site, what_it_is):
        assert site in read(SCANNER), f"{what_it_is} no longer spends timeout_ms"

    def test_there_are_no_others(self):
        scanner = read(SCANNER)
        spent = scanner.count("timeout=timeout_ms") + scanner.count(
            "asyncio.timeout(timeout_ms"
        )
        assert spent == BUDGETS_SPENT
