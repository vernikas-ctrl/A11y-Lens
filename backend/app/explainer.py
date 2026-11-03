"""Turns axe-core findings into explanations a person can act on.

Phase 5. This is the only module in the app that knows the Claude API exists.
`app.scanner` knows about browsers and nothing else; this knows about the model
and nothing else; `app.main` is the one place they meet. That split is what
makes the degraded path in `docs/api-contract.md` section 2.3 almost free: by
the time anything here runs, a complete and valid report already exists, so
every failure below can be answered by handing that report back untouched.

**Nothing in here raises.** A scan that found ten real problems is useful on
its own, and losing it because an API call failed would be the worst possible
trade. Failures are logged and turn into `explanations_available: false`.

Three things to know before changing it:

1. **The prompt lives in `app/prompts/explain_system.txt`,** not in this file,
   and `docs/prompt.md` explains the design and quotes it in full. A test
   fails if those two drift apart.

2. **Two caches, with different keys** (task 5.8, and section 6 of
   `docs/prompt.md`). The prose describing a rule is the same everywhere that
   rule is broken, so it is cached by rule id. A corrected snippet is specific
   to the element it corrects -- `logo.png` and `team-photo.jpg` need
   different alt text -- so it is cached by rule id **and** the element's
   HTML. Caching snippets by rule alone would show a developer a fix belonging
   to some other element, which is exactly the confident wrongness this
   feature is supposed to avoid.

3. **An issue gets both `explanation` and `fix`, or neither.** The contract
   requires that pairing, so anything half-answered is emitted as a pair of
   nulls rather than half-filled.
"""

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from app.scanner import Explanation, Fix, Issue, Report

logger = logging.getLogger("a11y_lens")

SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "explain_system.txt"

# Budget for the answer, which on this model has to cover thinking tokens as
# well as the JSON. Measured in task 5.11; these numbers are deliberately
# generous, because the cost of a too-small ceiling is a truncated answer and
# a wasted call, while the cost of a too-large one is nothing at all -- you are
# billed for tokens produced, not for the ceiling.
MAX_TOKENS_BASE = 2_000
MAX_TOKENS_PER_FIX = 400
MAX_TOKENS_PER_PROSE = 300
MAX_TOKENS_CEILING = 32_000

# Stop reasons that mean there is a complete answer to read. Anything else --
# `max_tokens`, `refusal` -- means the content is unusable, and reading it
# anyway is how you end up showing somebody half a sentence.
GOOD_STOP_REASONS = ("end_turn", "stop_sequence")

UNAVAILABLE_API = "api_unavailable"


# --- What we ask the model to return ----------------------------------------
#
# These are pydantic models rather than hand-written JSON Schema because the
# SDK turns them into the schema itself, and `messages.parse()` hands back a
# validated instance. There is no `json.loads` of a model response anywhere in
# this file: a reply that does not fit the schema is the API's problem to
# reject, not ours to discover halfway through rendering a page.
#
# The descriptions are not documentation. They are sent to the model as part of
# the schema, so they are instructions, and they are kept short because the
# reasoning behind them is in the system prompt.


class AnswerProse(BaseModel):
    """The `explanation` object of the contract: what is wrong, and for whom."""

    what: str = Field(description="What is wrong with this element, in one or two plain sentences.")
    who: str = Field(description="Who is affected and what happens to them, in one or two plain sentences.")


class AnswerFix(BaseModel):
    """The `fix` object of the contract, plus the ref that ties it to an issue."""

    ref: str = Field(description="The ref of the element this fix is for, copied exactly from the input.")
    language: Literal["html", "css"] = Field(description="html for markup, css for a rule set.")
    snippet: str = Field(description="The corrected code, ready to copy.")
    assumptions: list[str] = Field(
        description="One sentence for every fact invented because the input could not "
                    "say. Empty only when the fix involved no guessing."
    )


class AnswerRule(BaseModel):
    rule_id: str = Field(description="The rule id, copied exactly from the input.")
    explanation: AnswerProse | None = Field(
        description="The prose for this rule, or null when the input said prose_needed was false."
    )
    fixes: list[AnswerFix] = Field(description="One fix per element given for this rule.")


class Answer(BaseModel):
    rules: list[AnswerRule]


# --- The caches -------------------------------------------------------------


@dataclass
class Counters:
    """Evidence that the caches work, which task 5.8 asks to be provable.

    A counter rather than a log line only: a test can assert on a number, and
    `scanning the same URL twice makes no second API call` is a claim worth
    holding the code to automatically rather than by reading logs.
    """

    api_calls: int = 0
    prose_hits: int = 0
    prose_misses: int = 0
    fix_hits: int = 0
    fix_misses: int = 0
    # Elements asked about once because an identical one was already in this
    # same request. Separate from `fix_hits`, which means the cache answered.
    fix_deduped: int = 0
    failures: int = 0

    # Totals across every call this process has made, straight from the API's
    # own `usage`. Task 5.9's "done when" is that `cache_read_tokens` is above
    # zero on the second scan, and task 5.11 costs a scan out of these -- both
    # want a number a test or a script can read, not a line in a log file.
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class Cache:
    """In-process, and therefore empty again after a restart.

    Deliberate: a dictionary costs nothing to operate and cannot be wrong,
    while a persistent cache would need invalidating every time the prompt
    changes -- and the prompt is going to change. The thing it protects against
    is paying twice inside one session, which is the common case when somebody
    is trying the tool out.
    """

    prose: dict[str, Explanation] = field(default_factory=dict)
    fixes: dict[tuple[str, str], Fix] = field(default_factory=dict)
    counters: Counters = field(default_factory=Counters)

    def fix_key(self, rule_id: str, html: str) -> tuple[str, str]:
        """Hash the HTML rather than keying on it directly.

        An element's outer HTML runs to 500 characters, and holding thousands
        of those as dictionary keys for the life of the process is memory spent
        on nothing: the key only ever needs to answer "same element or not".
        """
        digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
        return (rule_id, digest)


@lru_cache(maxsize=1)
def system_prompt() -> str:
    """The system prompt, read once.

    Cached because it is marked for prompt caching on the API side, and that is
    a byte-for-byte prefix match: re-reading the file per request would be
    harmless here, but anything that could introduce a stray difference between
    one request and the next is worth removing on principle.
    """
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


# --- Building the request ----------------------------------------------------


def _plan(issues: list[Issue], cache: Cache) -> list[dict]:
    """Work out what still has to be asked for, grouped by rule.

    Returns the `rules` payload: only rules with at least one element whose fix
    is not already cached, and `prose_needed` set only where the prose for that
    rule is missing too. A rule whose every element is already answered does
    not appear at all, which is how scanning the same page twice sends nothing.
    """
    order: list[str] = []
    grouped: dict[str, list[Issue]] = {}
    for issue in issues:
        rule_id = issue["rule_id"]
        if rule_id not in grouped:
            grouped[rule_id] = []
            order.append(rule_id)
        grouped[rule_id].append(issue)

    payload = []
    for rule_id in order:
        members = grouped[rule_id]
        wanted = []
        # Two elements with byte-identical HTML are the same question, and a
        # page built from a template has plenty of those -- the same unlabelled
        # icon button in forty table rows. The cache alone would not catch them,
        # because none of them is in it yet when the request is built: they are
        # all misses in the same pass. So they are deduplicated here, asked
        # about once, and both get the one answer when the cache is read back.
        asked: set[tuple[str, str]] = set()
        for issue in members:
            key = cache.fix_key(rule_id, issue["html"])
            if key in cache.fixes:
                cache.counters.fix_hits += 1
            elif key in asked:
                cache.counters.fix_deduped += 1
            else:
                cache.counters.fix_misses += 1
                asked.add(key)
                wanted.append(issue)

        if not wanted:
            continue

        prose_needed = rule_id not in cache.prose
        if prose_needed:
            cache.counters.prose_misses += 1
        else:
            cache.counters.prose_hits += 1

        first = members[0]
        payload.append(
            {
                "rule_id": rule_id,
                "severity": first["severity"],
                "wcag": first["wcag"],
                "help_url": first["reference_url"],
                "prose_needed": prose_needed,
                "elements": [
                    {
                        "ref": issue["id"],
                        "selector": issue["selector"],
                        "html": issue["html"],
                    }
                    for issue in wanted
                ],
            }
        )
    return payload


def _max_tokens(payload: list[dict]) -> int:
    fixes = sum(len(rule["elements"]) for rule in payload)
    prose = sum(1 for rule in payload if rule["prose_needed"])
    budget = MAX_TOKENS_BASE + fixes * MAX_TOKENS_PER_FIX + prose * MAX_TOKENS_PER_PROSE
    return min(budget, MAX_TOKENS_CEILING)


def _user_message(report: Report, payload: list[dict]) -> str:
    """The volatile half of the request, and therefore the last thing in it.

    `sort_keys` is off on purpose: the key order here is written out by hand
    above and is already stable. What matters for the cache is that nothing
    *before* this changes, and that is the system prompt.
    """
    return json.dumps(
        {
            "page": {"url": report["url"], "title": report["page_title"]},
            "rules": payload,
        },
        ensure_ascii=False,
        indent=1,
    )


# --- Reading the answer back -------------------------------------------------


def _store_fixes(answer: Answer, cache: Cache, html_by_ref: dict[str, str]) -> None:
    """Cache each returned fix under the element it belongs to.

    The fix cache key needs the element's HTML, and the model only sends back a
    ref, so the mapping from ref to HTML has to be carried over from the
    request. That is `html_by_ref`, built where the request is built -- not
    looked up from the report again, because a ref the model invented must not
    find a match.
    """
    for rule in answer.rules:
        if rule.explanation is not None:
            cache.prose[rule.rule_id] = Explanation(
                what=rule.explanation.what.strip(),
                who=rule.explanation.who.strip(),
            )
        for fix in rule.fixes:
            html = html_by_ref.get(fix.ref)
            if html is None:
                logger.warning(
                    "the model returned a fix for an element that was not sent; dropping it"
                )
                continue
            cache.fixes[cache.fix_key(rule.rule_id, html)] = Fix(
                language=fix.language,
                snippet=fix.snippet.strip(),
                assumptions=[line.strip() for line in fix.assumptions if line.strip()],
            )


def _fill_from_cache(issues: list[Issue], cache: Cache) -> int:
    """Attach what the caches hold, and return how many issues got both halves.

    Both halves or neither: the contract says `explanation` and `fix` are null
    together or populated together, so an issue with a cached fix but no cached
    prose is left empty rather than half-dressed.
    """
    filled = 0
    for issue in issues:
        prose = cache.prose.get(issue["rule_id"])
        fix = cache.fixes.get(cache.fix_key(issue["rule_id"], issue["html"]))
        if prose is None or fix is None:
            issue["explanation"] = None
            issue["fix"] = None
            continue
        issue["explanation"] = prose
        issue["fix"] = fix
        filled += 1
    return filled


# --- The explainer -----------------------------------------------------------


class Explainer:
    """Holds one API client for the lifetime of the server, and one cache.

    Mirrors `Scanner` on purpose: both are started and stopped by the lifespan
    in `app.main`, so there is one shape to learn rather than two. The client
    pools HTTP connections, which is the same argument as reusing the browser,
    at a much smaller scale.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        effort: str,
        timeout_ms: int,
        enabled: bool = True,
        client_factory: Callable[..., object] | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._effort = effort
        self._timeout_ms = timeout_ms
        # False when the API key is still the placeholder. The request would
        # fail with a 401 anyway; not making it keeps the logs honest and the
        # failure instant rather than a round trip away.
        self._enabled = enabled
        # The seam the tests use. Tests must never reach the real API -- slow,
        # flaky, and it would spend money on every CI run -- so the client is
        # built through a factory that a test can replace with a stub, rather
        # than constructed inline where only monkeypatching could reach it.
        self._client_factory = client_factory or anthropic.AsyncAnthropic
        self._client: object | None = None
        self.cache = Cache()

    @property
    def is_running(self) -> bool:
        return self._client is not None

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def start(self) -> None:
        if not self._enabled:
            logger.warning(
                "explanations are off: ANTHROPIC_API_KEY is still the placeholder. "
                "Scans will return findings with explanations marked unavailable."
            )
            return
        self._client = self._client_factory(api_key=self._api_key)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def explain(self, report: Report) -> Report:
        """Fill in `explanation` and `fix` on every issue it can.

        Returns the same report object, modified. Never raises: on any failure
        the report comes back with `explanations_available: false` and a reason,
        which is the contract's degraded success and still a 200.
        """
        issues = report["issues"]

        if not issues:
            # A page with nothing wrong has nothing to explain, and saying
            # "explanations unavailable" about an empty list would be a lie.
            # Costs nothing, which is the point.
            report["explanations_available"] = True
            report.pop("explanations_unavailable_reason", None)
            return report

        if not self._enabled or self._client is None:
            return _degrade(report, UNAVAILABLE_API)

        payload = _plan(issues, self.cache)
        html_by_ref = {
            element["ref"]: element["html"]
            for rule in payload
            for element in rule["elements"]
        }

        if payload:
            try:
                answer = await self._ask(report, payload)
            except _ExplainFailed:
                self.cache.counters.failures += 1
                # Anything already in cache is still worth attaching: a second
                # scan of a page the first scan explained should not lose its
                # explanations because the API happens to be down now.
                if _fill_from_cache(issues, self.cache) == 0:
                    return _degrade(report, UNAVAILABLE_API)
                report["explanations_available"] = True
                report.pop("explanations_unavailable_reason", None)
                return report
            _store_fixes(answer, self.cache, html_by_ref)

        filled = _fill_from_cache(issues, self.cache)
        if filled == 0:
            return _degrade(report, UNAVAILABLE_API)

        if filled < len(issues):
            # Not a failure, but worth seeing in the log: it means the model
            # left something out that the schema asked for.
            logger.warning(
                "explained %d of %d issues; the rest are missing a half and were left blank",
                filled,
                len(issues),
            )

        report["explanations_available"] = True
        report.pop("explanations_unavailable_reason", None)
        return report

    async def _ask(self, report: Report, payload: list[dict]) -> Answer:
        """One request. Raises `_ExplainFailed` for anything that goes wrong.

        Every failure is logged with enough to act on and nothing more: no API
        key, and no exception text pasted into a user-visible field.
        """
        assert self._client is not None
        timeout_s = self._timeout_ms / 1000

        try:
            async with asyncio.timeout(timeout_s):
                message = await self._client.messages.parse(
                    model=self._model,
                    max_tokens=_max_tokens(payload),
                    # A list of one block so the cache marker has somewhere to
                    # go, and first in the request because prompt caching is a
                    # prefix match: stable content first, the per-scan JSON
                    # last. Task 5.9.
                    system=[
                        {
                            "type": "text",
                            "text": system_prompt(),
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": _user_message(report, payload)}],
                    # Thinking cannot be switched off on this model, and it
                    # bills as output. Effort is the dial, and it is
                    # configuration: see ANTHROPIC_EFFORT in .env.example.
                    output_config={"effort": self._effort},
                    output_format=Answer,
                    timeout=timeout_s,
                )
        # Most specific first. AuthenticationError, NotFoundError and
        # RateLimitError are all subclasses of APIStatusError, so putting the
        # broad one above them would swallow all three and log the wrong cause.
        except anthropic.NotFoundError:
            raise _failed("model %r does not exist; check ANTHROPIC_MODEL", self._model)
        except anthropic.AuthenticationError:
            raise _failed("the API key was rejected; check ANTHROPIC_API_KEY")
        except anthropic.PermissionDeniedError:
            raise _failed("the API key is not allowed to use this model")
        except anthropic.RateLimitError:
            raise _failed("rate limited by the API")
        except anthropic.BadRequestError as exc:
            # The one case where the message matters: a 400 is usually our own
            # request being wrong, and it is the only exception text that says
            # which field. It never reaches the user, only the server log.
            raise _failed("the API rejected the request: %s", exc.message)
        except anthropic.APIStatusError as exc:
            raise _failed("the API returned %s", exc.status_code)
        except anthropic.APIConnectionError:
            raise _failed("could not reach the API")
        except TimeoutError:
            # asyncio.timeout, not the SDK: the whole call took too long.
            raise _failed("the explanation call took longer than %dms", self._timeout_ms)

        # Checked before the content is touched. `refusal` means there is no
        # answer in there, and `max_tokens` means the JSON stops mid-string.
        if message.stop_reason not in GOOD_STOP_REASONS:
            raise _failed("the model stopped early: stop_reason=%s", message.stop_reason)

        if message.parsed_output is None:
            raise _failed("the reply contained no structured output")

        usage = message.usage
        counters = self.cache.counters
        counters.input_tokens += usage.input_tokens or 0
        counters.output_tokens += usage.output_tokens or 0
        # getattr: these two are absent on a response from a request that was
        # never eligible for caching, and `or 0` because the API sends null
        # rather than zero when a field does not apply.
        counters.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        counters.cache_write_tokens += (
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        )
        logger.info(
            "explained %d rule(s): %s in, %s out, %s cache read, %s cache write",
            len(payload),
            usage.input_tokens,
            usage.output_tokens,
            getattr(usage, "cache_read_input_tokens", None),
            getattr(usage, "cache_creation_input_tokens", None),
        )
        self.cache.counters.api_calls += 1
        return message.parsed_output


class _ExplainFailed(Exception):
    """Internal. Never leaves this module, never reaches a response body."""


def _failed(message: str, *args: object) -> _ExplainFailed:
    logger.warning("explanations unavailable: " + message, *args)
    return _ExplainFailed()


def _degrade(report: Report, reason: str) -> Report:
    """The contract's section 2.3: findings kept, explanations marked missing."""
    for issue in report["issues"]:
        issue["explanation"] = None
        issue["fix"] = None
    report["explanations_available"] = False
    report["explanations_unavailable_reason"] = reason
    return report
