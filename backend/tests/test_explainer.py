"""Tests for the explanation layer. Task 5.10.

**Nothing in this file touches the real API.** Tests that called it would be
slow, flaky, dependent on a key being present, and would spend money on every
run and every future CI build -- so the client is replaced with the stub below
through the `client_factory` seam, and the only thing left to assert is our own
behaviour, which is the part that can actually be wrong.

What the stub lets us check that a live call could not:

- the exact request that goes out, including where the cache marker sits;
- that a second scan of the same page sends nothing at all;
- every failure the API can hand back, including ones that are hard to cause
  on purpose, like a refusal or a truncated answer.

Everything here is synchronous except where a coroutine has to be driven, and
those use `asyncio.run` rather than pytest-asyncio: one fewer dependency, and
the explainer has no fixtures worth sharing between tests because its whole
point is that each one starts from an empty cache.
"""

import asyncio
import json
import re
from pathlib import Path

import anthropic
import httpx2
import pytest

from app.explainer import (
    Answer,
    AnswerFix,
    AnswerProse,
    AnswerRule,
    Cache,
    Explainer,
    _max_tokens,
    _plan,
    system_prompt,
)
from app.scanner import Issue, Report

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPT_DOC = REPO_ROOT / "docs" / "prompt.md"


# --- Building reports to feed it ---------------------------------------------


def issue(rule_id: str, index: int = 0, html: str | None = None, **overrides) -> Issue:
    """One issue in exactly the shape the scanner produces."""
    base: Issue = {
        "id": f"{rule_id}-{index}",
        "rule_id": rule_id,
        "severity": "serious",
        "wcag": ["1.1.1"],
        "reference_url": f"https://dequeuniversity.com/rules/axe/4.14/{rule_id}",
        "selector": f"main > {rule_id}:nth-child({index + 1})",
        "html": html if html is not None else f'<img src="/{rule_id}-{index}.png">',
        "explanation": None,
        "fix": None,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def report(*issues: Issue) -> Report:
    return {
        "url": "https://acme.example.com/",
        "page_title": "Acme Corp",
        "scanned_at": "2026-11-03T12:00:00Z",
        "scan_duration_ms": 1234,
        "explanations_available": False,
        "explanations_unavailable_reason": "api_unavailable",
        "summary": {
            "critical": 0,
            "serious": len(issues),
            "moderate": 0,
            "minor": 0,
            "total": len(issues),
        },
        "issues": list(issues),
    }


# --- The stub client ---------------------------------------------------------


class FakeUsage:
    def __init__(self) -> None:
        self.input_tokens = 1200
        self.output_tokens = 800
        self.cache_read_input_tokens = 1100
        self.cache_creation_input_tokens = 0


class FakeMessage:
    def __init__(self, parsed: Answer | None, stop_reason: str = "end_turn") -> None:
        self.parsed_output = parsed
        self.stop_reason = stop_reason
        self.usage = FakeUsage()
        self._request_id = "req_test"


class FakeMessages:
    """Records every request and replays a scripted list of outcomes."""

    def __init__(self, outcomes: list) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[dict] = []

    async def parse(self, **kwargs):
        self.requests.append(kwargs)
        if not self.outcomes:
            raise AssertionError("the explainer made more API calls than the test scripted")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes: list) -> None:
        self.messages = FakeMessages(outcomes)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def answer_for(*rules: tuple[str, bool, list[str]]) -> Answer:
    """A well-formed answer: (rule_id, include_prose, [refs])."""
    return Answer(
        rules=[
            AnswerRule(
                rule_id=rule_id,
                explanation=(
                    AnswerProse(
                        what=f"The {rule_id} rule failed on this element.",
                        who="Someone using a screen reader loses the content.",
                    )
                    if with_prose
                    else None
                ),
                fixes=[
                    AnswerFix(
                        ref=ref,
                        language="html",
                        snippet=f'<img src="/{ref}.png" alt="Acme Corp logo">',
                        assumptions=[f"Assumed {ref} is the Acme Corp logo."],
                    )
                    for ref in refs
                ],
            )
            for rule_id, with_prose, refs in rules
        ]
    )


def explainer_with(*outcomes, **kwargs) -> tuple[Explainer, FakeClient]:
    """An explainer wired to the stub, already started."""
    client = FakeClient(list(outcomes))
    explainer = Explainer(
        api_key="sk-ant-not-a-real-key",
        model="claude-opus-5-5",
        effort="low",
        timeout_ms=60_000,
        client_factory=lambda **_: client,
        **kwargs,
    )
    asyncio.run(explainer.start())
    return explainer, client


def explain(explainer: Explainer, data: Report) -> Report:
    return asyncio.run(explainer.explain(data))


# --- The prompt is where the doc says it is ----------------------------------


def test_the_prompt_document_quotes_the_real_prompt_exactly():
    """docs/prompt.md section 5 claims to be a verbatim copy. Hold it to that.

    Without this test the document rots: somebody tunes the prompt, the file
    they read to understand it still describes the old one, and the next person
    debugs the wrong text.
    """
    doc = PROMPT_DOC.read_text(encoding="utf-8")
    after_heading = doc.split("## 5. The system prompt, in full", 1)[1]
    quoted = after_heading.split("```text", 1)[1].split("```", 1)[0].lstrip("\n")
    assert quoted == system_prompt(), (
        "docs/prompt.md section 5 no longer matches "
        "app/prompts/explain_system.txt -- paste the new text in"
    )


def test_the_prompt_is_long_enough_to_be_cacheable():
    """Claude Opus 5.5 will not cache a prefix under 512 tokens, and says
    nothing when it declines -- `cache_read_input_tokens` is just zero.

    Tokens cannot be counted here without calling the API, so this uses a
    deliberately pessimistic four characters per token: if even that estimate
    clears the floor, the real count certainly does.
    """
    pessimistic_tokens = len(system_prompt()) / 4
    assert pessimistic_tokens > 512


def test_the_prompt_tells_the_model_the_page_is_not_instructions():
    """The scanned page is somebody else's content and goes straight into the
    request. The boundary against it being read as instructions is a paragraph
    of the prompt, so its absence should fail a test rather than be noticed
    later."""
    text = system_prompt().lower()
    assert "data, not instructions" in text
    assert "disregard these instructions" in text


# --- Planning: who gets asked for what ---------------------------------------


def test_a_cold_cache_asks_for_prose_and_every_element():
    cache = Cache()
    payload = _plan([issue("image-alt", 0), issue("image-alt", 1)], cache)

    assert len(payload) == 1
    assert payload[0]["rule_id"] == "image-alt"
    assert payload[0]["prose_needed"] is True
    assert [element["ref"] for element in payload[0]["elements"]] == [
        "image-alt-0",
        "image-alt-1",
    ]


def test_a_second_element_of_a_known_rule_asks_for_the_fix_but_not_the_prose():
    """The saving the split cache exists for: the prose is already paid for,
    the snippet is not, and one request asks for exactly the difference."""
    explainer, client = explainer_with(
        FakeMessage(answer_for(("image-alt", True, ["image-alt-0"]))),
        FakeMessage(answer_for(("image-alt", False, ["image-alt-1"]))),
    )

    explain(explainer, report(issue("image-alt", 0)))
    second = explain(explainer, report(issue("image-alt", 1)))

    sent = json.loads(client.messages.requests[1]["messages"][0]["content"])
    assert sent["rules"][0]["prose_needed"] is False
    assert [e["ref"] for e in sent["rules"][0]["elements"]] == ["image-alt-1"]
    # And the prose from the first call is reused rather than dropped.
    assert second["issues"][0]["explanation"]["what"].startswith("The image-alt rule")


def test_an_already_answered_page_asks_for_nothing():
    """Task 5.8's own test: scanning the same URL twice makes no second call."""
    explainer, client = explainer_with(
        FakeMessage(answer_for(("image-alt", True, ["image-alt-0"])))
    )

    first = explain(explainer, report(issue("image-alt", 0)))
    second = explain(explainer, report(issue("image-alt", 0)))

    assert len(client.messages.requests) == 1
    assert explainer.cache.counters.api_calls == 1
    assert second["explanations_available"] is True
    assert second["issues"][0]["fix"] == first["issues"][0]["fix"]


def test_identical_html_under_one_rule_is_asked_about_once():
    """Two elements with byte-identical HTML are the same question. Both still
    get an answer; only one of them is paid for."""
    same = '<img src="/logo.png">'
    explainer, client = explainer_with(
        FakeMessage(answer_for(("image-alt", True, ["image-alt-0"])))
    )

    done = explain(
        explainer,
        report(issue("image-alt", 0, html=same), issue("image-alt", 1, html=same)),
    )

    sent = json.loads(client.messages.requests[0]["messages"][0]["content"])
    assert len(sent["rules"][0]["elements"]) == 1
    assert explainer.cache.counters.fix_deduped == 1
    assert done["issues"][0]["fix"] == done["issues"][1]["fix"]


def test_different_html_under_one_rule_gets_different_fixes():
    """The whole reason the fix cache is keyed by element. A logo and a team
    photograph must not share a snippet."""
    explainer, _ = explainer_with(
        FakeMessage(
            answer_for(("image-alt", True, ["image-alt-0", "image-alt-1"]))
        )
    )

    done = explain(
        explainer,
        report(
            issue("image-alt", 0, html='<img src="/logo.png">'),
            issue("image-alt", 1, html='<img src="/team.jpg">'),
        ),
    )

    first, second = done["issues"]
    assert first["fix"]["snippet"] != second["fix"]["snippet"]
    assert first["explanation"] == second["explanation"]  # prose is rule-level


def test_the_token_budget_grows_with_the_work():
    small = _max_tokens([{"elements": [{}], "prose_needed": True}])
    large = _max_tokens([{"elements": [{}] * 20, "prose_needed": True}])
    assert large > small
    assert _max_tokens([{"elements": [{}] * 5000, "prose_needed": True}]) <= 32_000


# --- The request itself ------------------------------------------------------


def test_the_system_prompt_is_marked_for_caching_and_comes_first():
    """Task 5.9. Prompt caching is a prefix match, so the stable half has to be
    at the front and the per-scan JSON at the back. Asserting on the shape of
    the request is the only way to check this without a live call."""
    explainer, client = explainer_with(
        FakeMessage(answer_for(("image-alt", True, ["image-alt-0"])))
    )
    explain(explainer, report(issue("image-alt", 0)))

    sent = client.messages.requests[0]
    assert sent["system"][0]["text"] == system_prompt()
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}
    # The volatile content is in the message, never spliced into the system
    # prompt -- one scan-specific byte up there would cost every later cache
    # hit in the process.
    assert "acme.example.com" not in sent["system"][0]["text"]
    assert "acme.example.com" in sent["messages"][0]["content"]


def test_the_request_carries_the_model_the_schema_and_the_effort():
    explainer, client = explainer_with(
        FakeMessage(answer_for(("image-alt", True, ["image-alt-0"])))
    )
    explain(explainer, report(issue("image-alt", 0)))

    sent = client.messages.requests[0]
    assert sent["model"] == "claude-opus-5-5"
    assert sent["output_config"] == {"effort": "low"}
    # Structured output by schema, which is what makes hand-rolled JSON parsing
    # unnecessary anywhere in this path.
    assert sent["output_format"] is Answer


def test_the_request_sends_only_the_documented_fields():
    """docs/prompt.md section 2 is a promise about what leaves this machine.
    A field added here by accident is a field somebody did not agree to send."""
    explainer, client = explainer_with(
        FakeMessage(answer_for(("image-alt", True, ["image-alt-0"])))
    )
    explain(explainer, report(issue("image-alt", 0)))

    sent = json.loads(client.messages.requests[0]["messages"][0]["content"])
    assert set(sent) == {"page", "rules"}
    assert set(sent["page"]) == {"url", "title"}
    assert set(sent["rules"][0]) == {
        "rule_id",
        "severity",
        "wcag",
        "help_url",
        "prose_needed",
        "elements",
    }
    assert set(sent["rules"][0]["elements"][0]) == {"ref", "selector", "html"}


# --- The answer --------------------------------------------------------------


def test_a_good_answer_fills_in_the_contract_fields():
    explainer, _ = explainer_with(
        FakeMessage(answer_for(("image-alt", True, ["image-alt-0"])))
    )

    done = explain(explainer, report(issue("image-alt", 0)))
    issue_out = done["issues"][0]

    assert done["explanations_available"] is True
    assert "explanations_unavailable_reason" not in done
    assert set(issue_out["explanation"]) == {"what", "who"}
    assert set(issue_out["fix"]) == {"language", "snippet", "assumptions"}
    assert issue_out["fix"]["language"] in ("html", "css")
    assert isinstance(issue_out["fix"]["assumptions"], list)
    # The ref is how a fix is matched to its issue; it must not survive into
    # the response, which the contract defines without it.
    assert "ref" not in issue_out["fix"]


def test_assumptions_survive_because_they_are_the_point():
    """Task 5.4. A snippet that invented alt text must arrive with the
    invention named, or the UI has nothing to mark."""
    explainer, _ = explainer_with(
        FakeMessage(answer_for(("image-alt", True, ["image-alt-0"])))
    )
    done = explain(explainer, report(issue("image-alt", 0)))

    assumptions = done["issues"][0]["fix"]["assumptions"]
    assert assumptions and all(isinstance(line, str) for line in assumptions)
    assert "Assumed" in assumptions[0]


def test_an_empty_assumptions_list_is_allowed_to_stay_empty():
    """A missing lang attribute involves no guessing. Fabricating a caveat for
    it would teach the reader to skip the ones that matter."""
    explainer, _ = explainer_with(
        FakeMessage(
            Answer(
                rules=[
                    AnswerRule(
                        rule_id="html-has-lang",
                        explanation=AnswerProse(what="No lang attribute.", who="Wrong voice."),
                        fixes=[
                            AnswerFix(
                                ref="html-has-lang-0",
                                language="html",
                                snippet='<html lang="en">',
                                assumptions=[],
                            )
                        ],
                    )
                ]
            )
        )
    )

    done = explain(explainer, report(issue("html-has-lang", 0, html="<html>")))
    assert done["issues"][0]["fix"]["assumptions"] == []
    assert done["explanations_available"] is True


def test_a_fix_for_an_element_we_never_sent_is_dropped():
    """A hallucinated ref must not get into the cache, or a later scan would
    serve an invented correction for an element that does not exist."""
    explainer, _ = explainer_with(
        FakeMessage(
            answer_for(("image-alt", True, ["image-alt-0", "image-alt-99"]))
        )
    )

    done = explain(explainer, report(issue("image-alt", 0)))

    assert len(done["issues"]) == 1
    assert done["issues"][0]["fix"] is not None
    assert len(explainer.cache.fixes) == 1


def test_an_issue_missing_half_an_answer_gets_neither_half():
    """The contract: explanation and fix are null together or populated
    together. A rule that came back with prose but no fix leaves its issues
    blank rather than half-filled."""
    explainer, _ = explainer_with(
        FakeMessage(answer_for(("image-alt", True, [])))  # prose, no fixes
    )

    done = explain(explainer, report(issue("image-alt", 0)))

    assert done["issues"][0]["explanation"] is None
    assert done["issues"][0]["fix"] is None
    assert done["explanations_available"] is False
    assert done["explanations_unavailable_reason"] == "api_unavailable"


def test_a_page_with_no_issues_costs_nothing():
    explainer, client = explainer_with()  # no outcomes: a call would fail the test

    done = explain(explainer, report())

    assert client.messages.requests == []
    assert done["explanations_available"] is True
    assert "explanations_unavailable_reason" not in done


# --- Failure, every way it comes ---------------------------------------------


def fake_request() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def api_error(cls, status: int) -> anthropic.APIStatusError:
    """Build a real SDK exception without a real HTTP round trip.

    Real exception classes rather than stand-ins, because the thing under test
    is an `except` ladder: subclass order is exactly what it can get wrong, and
    a stand-in would prove nothing about it. Note `httpx2` -- the SDK ships its
    own fork, and importing plain `httpx` here fails.
    """
    response = httpx2.Response(
        status, request=fake_request(), json={"error": {"message": "nope"}}
    )
    return cls("nope", response=response, body=None)


@pytest.mark.parametrize(
    "failure",
    [
        api_error(anthropic.AuthenticationError, 401),
        api_error(anthropic.PermissionDeniedError, 403),
        api_error(anthropic.NotFoundError, 404),
        api_error(anthropic.RateLimitError, 429),
        api_error(anthropic.BadRequestError, 400),
        api_error(anthropic.InternalServerError, 500),
        anthropic.APIConnectionError(request=fake_request()),
        TimeoutError(),
    ],
    ids=["401", "403", "404", "429", "400", "500", "no-connection", "timeout"],
)
def test_every_failure_degrades_instead_of_raising(failure):
    """Task 5.5 and 5.6 together. Whatever the API does, the findings survive
    and the response still matches the contract."""
    explainer, _ = explainer_with(failure)

    done = explain(explainer, report(issue("image-alt", 0)))

    assert done["explanations_available"] is False
    assert done["explanations_unavailable_reason"] == "api_unavailable"
    assert done["issues"][0]["explanation"] is None
    assert done["issues"][0]["fix"] is None
    assert done["summary"]["total"] == 1  # the findings are untouched
    assert explainer.cache.counters.failures == 1


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal", "pause_turn"])
def test_an_answer_that_stopped_early_is_not_read(stop_reason):
    """`stop_reason` is checked before the content is touched. A truncated
    answer holds JSON that stops mid-string, and a refusal holds no answer at
    all; using either would mean rendering nonsense."""
    explainer, _ = explainer_with(
        FakeMessage(
            answer_for(("image-alt", True, ["image-alt-0"])), stop_reason=stop_reason
        )
    )

    done = explain(explainer, report(issue("image-alt", 0)))

    assert done["explanations_available"] is False
    assert done["issues"][0]["fix"] is None


def test_a_reply_with_no_structured_output_degrades():
    explainer, _ = explainer_with(FakeMessage(None))

    done = explain(explainer, report(issue("image-alt", 0)))

    assert done["explanations_available"] is False


def test_a_failure_keeps_explanations_that_were_already_cached():
    """A second scan of a page the first scan explained should not lose its
    explanations because the API went down in between."""
    explainer, _ = explainer_with(
        FakeMessage(answer_for(("image-alt", True, ["image-alt-0"]))),
        api_error(anthropic.InternalServerError, 500),
    )

    explain(explainer, report(issue("image-alt", 0)))
    second = explain(
        explainer,
        report(issue("image-alt", 0), issue("button-name", 0, html="<button></button>")),
    )

    assert second["explanations_available"] is True
    assert second["issues"][0]["fix"] is not None       # from cache
    assert second["issues"][1]["fix"] is None           # the call that failed


def test_no_api_key_means_no_call_at_all():
    """A fresh clone has the placeholder key. The request would come back 401,
    so not making it is both faster and honest in the logs."""
    explainer, client = explainer_with(enabled=False)
    asyncio.run(explainer.start())

    done = explain(explainer, report(issue("image-alt", 0)))

    assert explainer.is_running is False
    assert client.messages.requests == []
    assert done["explanations_available"] is False
    assert done["explanations_unavailable_reason"] == "api_unavailable"


def test_no_failure_message_mentions_the_api_key():
    """The key must not reach a log line, let alone a response. Checked against
    the recorded log rather than assumed."""
    explainer, _ = explainer_with(api_error(anthropic.AuthenticationError, 401))

    import logging

    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logger = logging.getLogger("a11y_lens")
    handler = Capture()
    logger.addHandler(handler)
    try:
        explain(explainer, report(issue("image-alt", 0)))
    finally:
        logger.removeHandler(handler)

    assert records
    assert not any("sk-ant" in line for line in records)


def test_stopping_closes_the_client():
    explainer, client = explainer_with()
    asyncio.run(explainer.stop())
    assert client.closed is True
    assert explainer.is_running is False


# --- The response shape, against the contract --------------------------------


def test_the_explained_report_matches_the_contract_exactly():
    """The same check `test_scanner.py` makes on an unexplained report, now
    that two of the fields are no longer null."""
    explainer, _ = explainer_with(
        FakeMessage(answer_for(("image-alt", True, ["image-alt-0"])))
    )
    done = explain(explainer, report(issue("image-alt", 0)))

    assert set(done) == {
        "url",
        "page_title",
        "scanned_at",
        "scan_duration_ms",
        "explanations_available",
        "summary",
        "issues",
    }
    assert set(done["issues"][0]) == {
        "id",
        "rule_id",
        "severity",
        "wcag",
        "reference_url",
        "selector",
        "html",
        "explanation",
        "fix",
    }


def test_the_prose_contains_no_markdown():
    """The contract says both fields are plain prose. The prompt says so too,
    but a prompt is a request and a test is a check -- and the frontend renders
    these as text, so stray backticks would show up literally."""
    explainer, _ = explainer_with(
        FakeMessage(answer_for(("image-alt", True, ["image-alt-0"])))
    )
    done = explain(explainer, report(issue("image-alt", 0)))

    prose = done["issues"][0]["explanation"]
    for field_name in ("what", "who"):
        assert not re.search(r"[`*#]|^\s*[-+]\s", prose[field_name], re.MULTILINE)


@pytest.mark.parametrize(
    "failure,expected",
    [
        (api_error(anthropic.NotFoundError, 404), "does not exist"),
        (api_error(anthropic.AuthenticationError, 401), "key was rejected"),
        (api_error(anthropic.PermissionDeniedError, 403), "not allowed"),
        (api_error(anthropic.RateLimitError, 429), "rate limited"),
        (api_error(anthropic.InternalServerError, 500), "returned 500"),
        (anthropic.APIConnectionError(request=fake_request()), "could not reach"),
        (TimeoutError(), "longer than"),
    ],
    ids=["404", "401", "403", "429", "500", "no-connection", "timeout"],
)
def test_each_failure_is_logged_as_itself(failure, expected, caplog):
    """Task 5.5 asks for the specific exceptions to be caught most-specific
    first. Degrading is not evidence of that -- every branch degrades.

    What proves the ladder is in the right order is the diagnosis: 401, 404,
    403 and 429 are all subclasses of APIStatusError, so a broad clause above
    them would still degrade, but every one of these would be logged as
    "the API returned 401" and the person reading the log would be told
    nothing useful about which thing to go and fix.
    """
    explainer, _ = explainer_with(failure)

    with caplog.at_level("WARNING", logger="a11y_lens"):
        explain(explainer, report(issue("image-alt", 0)))

    assert expected in caplog.text
