"""What does one scan actually cost? Task 5.11.

Runs a real scan, explains it for real, and prints the bill. Needs a working
API key in `backend/.env` and spends a few cents, which is the point: the
number in DECISIONS.md has to be measured, because every estimate of this that
does not come from the API's own `usage` has been wrong.

    cd backend
    .venv/Scripts/python.exe scripts/cost_check.py
    .venv/Scripts/python.exe scripts/cost_check.py --url https://www.bbc.co.uk

It scans the same page twice on purpose. The second pass is where the two
savings show up, and they are different savings that are easy to confuse:

- **Our cache** (task 5.8) means the second scan sends no request at all, so it
  costs nothing. That is the one that matters on a zero budget.
- **Prompt caching** (task 5.9) is the API's own, and only shows up when a
  request *is* sent: the system prompt is then billed at a twentieth of the
  input rate. To see it, use `--distinct`, which scans two different pages so
  the second request is real but shares the prompt prefix.

Token counts come from the API's `count_tokens` endpoint and from `usage` on
the real response. Never from a third-party tokenizer: `tiktoken` is OpenAI's
and undercounts Claude by 15-20%, more on code.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic  # noqa: E402

from app.config import ConfigError, get_settings  # noqa: E402
from app.explainer import (  # noqa: E402
    Answer,
    Explainer,
    _max_tokens,
    _plan,
    _user_message,
    system_prompt,
)
from app.scanner import Scanner  # noqa: E402

DEFAULT_URL = "https://example.com"
SECOND_URL = "https://www.iana.org/help/example-domains"

# Published prices per million tokens, Claude Opus 5.5, checked 3 November 2026.
# Hard-coded with a date rather than fetched: the cost of one scan is a fact
# about a moment, and a number that silently changes under a committed
# DECISIONS.md entry would make that entry a lie. Check the pricing page before
# trusting an old run of this script.
PRICES = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
}
MILLION = 1_000_000


def dollars(amount: float) -> str:
    """Six decimal places, because one scan costs cents and rounding to two
    would print $0.00 and teach the wrong lesson."""
    return f"${amount:.6f}"


def price_of(model: str, counters) -> float | None:
    prices = PRICES.get(model)
    if prices is None:
        return None
    return (
        counters.input_tokens * prices["input"]
        + counters.output_tokens * prices["output"]
        + counters.cache_read_tokens * prices["cache_read"]
        + counters.cache_write_tokens * prices["cache_write"]
    ) / MILLION


async def run(first_url: str, second_url: str, timeout_ms: int) -> int:
    try:
        settings = get_settings()
    except ConfigError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1

    if settings.uses_placeholder_api_key:
        print(
            "ANTHROPIC_API_KEY in backend/.env is still the placeholder, so "
            "there is nothing to measure.\nRun scripts/hello_claude.py first.",
            file=sys.stderr,
        )
        return 1

    scanner = Scanner()
    explainer = Explainer(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.anthropic_model,
        effort=settings.anthropic_effort,
        timeout_ms=settings.explain_timeout_ms,
    )

    await scanner.start()
    await explainer.start()
    counters = explainer.cache.counters

    try:
        print(f"Model:  {settings.anthropic_model}  (effort {settings.anthropic_effort})\n")

        # --- What the request looks like before it is sent -----------------
        report = await scanner.scan(first_url, timeout_ms=timeout_ms)
        issues = report["issues"]
        print(f"Scanned {first_url}")
        print(f"  {len(issues)} issue(s), {len({i['rule_id'] for i in issues})} distinct rule(s)")

        if not issues:
            print("\nNothing to explain on this page, so nothing to cost. "
                  "Try --url on a page with real problems.")
            return 0

        # Counted against the same model that will answer, because token counts
        # are model-specific.
        planned = _plan(issues, explainer.cache)
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
        counted = client.messages.count_tokens(
            model=settings.anthropic_model,
            system=[{"type": "text", "text": system_prompt()}],
            messages=[{"role": "user", "content": _user_message(report, planned)}],
        )
        prompt_only = client.messages.count_tokens(
            model=settings.anthropic_model,
            messages=[{"role": "user", "content": system_prompt()}],
        )
        print(f"\n  system prompt:    {prompt_only.input_tokens:>6} tokens"
              f"   (prompt caching needs 512 or more)")
        print(f"  whole request:    {counted.input_tokens:>6} tokens")
        print(f"  output ceiling:   {_max_tokens(planned):>6} tokens")

        # _plan has already recorded this pass in the counters, and the cache is
        # about to be consulted again by explain(). Reset so the printed numbers
        # describe the calls and not the dry run.
        explainer.cache.counters.fix_misses = 0
        explainer.cache.counters.prose_misses = 0

        # --- Scan one: everything is cold ----------------------------------
        await explainer.explain(report)
        after_first = (counters.input_tokens, counters.output_tokens)
        print(f"\nScan 1  ({'explained' if report['explanations_available'] else 'DEGRADED'})")
        print(f"  api calls:        {counters.api_calls}")
        print(f"  input:            {counters.input_tokens:>6} tokens")
        print(f"  output:           {counters.output_tokens:>6} tokens  (includes thinking)")
        print(f"  cache write:      {counters.cache_write_tokens:>6} tokens")
        print(f"  cache read:       {counters.cache_read_tokens:>6} tokens")
        first_cost = price_of(settings.anthropic_model, counters)
        if first_cost is not None:
            print(f"  cost:             {dollars(first_cost)}")

        # --- Scan two: the same page, which should cost nothing ------------
        again = await scanner.scan(first_url, timeout_ms=timeout_ms)
        await explainer.explain(again)
        print("\nScan 2, same page  (task 5.8: our cache)")
        print(f"  api calls so far: {counters.api_calls}")
        print(f"  new tokens:       {counters.input_tokens - after_first[0]} in, "
              f"{counters.output_tokens - after_first[1]} out")
        print(f"  explained:        {again['explanations_available']}")

        # --- Scan three: a different page, to see the API's own cache ------
        if second_url:
            other = await scanner.scan(second_url, timeout_ms=timeout_ms)
            before_read = counters.cache_read_tokens
            await explainer.explain(other)
            gained = counters.cache_read_tokens - before_read
            print(f"\nScan 3, {second_url}  (task 5.9: prompt caching)")
            print(f"  cache read:       {gained:>6} tokens on this call")
            if gained == 0:
                print("  cache read was zero -- the system prompt is either under "
                      "512 tokens\n  or something in the prefix changed between "
                      "requests.")

        total = price_of(settings.anthropic_model, counters)
        if total is None:
            print(f"\nNo price on file for {settings.anthropic_model}; tokens only.")
            return 0

        print(f"\nTotal for this run:  {dollars(total)}")
        print(f"One cold scan:       {dollars(first_cost or 0)}")
        print(f"100 cold scans:      {dollars((first_cost or 0) * 100)}")
        print(f"At DAILY_SCAN_LIMIT={settings.daily_scan_limit}: "
              f"{dollars((first_cost or 0) * settings.daily_scan_limit)} a day, worst case")
        print("\nWorst case means every scan cold and every rule unseen. Repeat "
              "visitors and\ncommon rules come out of the cache, so the real "
              "figure is lower -- but the\nworst case is the one the budget has "
              "to survive.")
        return 0
    finally:
        await explainer.stop()
        await scanner.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="page to scan and cost")
    parser.add_argument(
        "--distinct",
        default=SECOND_URL,
        help="a second, different page, to show prompt caching on a real request; "
             "pass an empty string to skip it",
    )
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    args = parser.parse_args()

    return asyncio.run(run(args.url, args.distinct, args.timeout_ms))


if __name__ == "__main__":
    raise SystemExit(main())
