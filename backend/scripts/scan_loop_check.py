"""Does repeated scanning leak? Task 4.6's second "Done when".

Task 4.6 asks for two things. That the second scan is faster than the first is
asserted by `tests/test_scan_endpoint.py`. The other -- that ten scans in a row
do not grow memory without bound -- is a measurement, not an assertion: there
is no threshold that is right on every machine, and a test that invented one
would fail on a busy laptop and teach us nothing.

So this prints the numbers and leaves the judgement to a person.

**What it measures.** Resident memory of this process and every process
descended from it, sampled after each scan, which is the whole Chromium tree.
Same approach as `memory_check.py` from Phase 1, and the same caveats apply:
summing per-process RSS over-counts memory shared between Chromium's
processes, and Windows accounts for resident memory differently from Linux.
These numbers are a shape, not a verdict.

**What to look for.** Memory climbing for the first few scans and then
levelling off is normal and fine -- that is caches filling. Memory climbing by
roughly the same amount on every scan is a leak, and the usual cause is a
browser context that was opened and never closed.

    cd backend
    .venv/Scripts/python.exe scripts/scan_loop_check.py
    .venv/Scripts/python.exe scripts/scan_loop_check.py --url https://example.com
    .venv/Scripts/python.exe scripts/scan_loop_check.py --scans 25

Defaults to the local test fixture, so it needs no internet and scans exactly
the same bytes every time -- which is what makes a change between scan 1 and
scan 10 attributable to us rather than to the page.
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.scanner import Scanner  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "broken.html"
MB = 1024 * 1024


def tree_memory_mb() -> tuple[float, int]:
    """Resident memory of this process and all its descendants, in MB."""
    process = psutil.Process(os.getpid())
    total = process.memory_info().rss
    count = 1
    for child in process.children(recursive=True):
        try:
            total += child.memory_info().rss
            count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Chromium starts and stops helper processes constantly; one
            # disappearing mid-measurement is normal, not an error.
            continue
    return total / MB, count


async def run(url: str, scans: int, timeout_ms: int) -> int:
    scanner = Scanner()

    baseline, _ = tree_memory_mb()
    print(f"Before the browser starts: {baseline:6.1f} MB")

    await scanner.start()
    after_launch, processes = tree_memory_mb()
    print(f"Browser launched:          {after_launch:6.1f} MB  ({processes} processes)")
    print(f"\nScanning {url}\n")
    print(f"{'scan':>4}  {'seconds':>8}  {'issues':>7}  {'MB':>7}  {'change':>8}  procs")

    previous = after_launch
    peak = after_launch
    durations = []

    try:
        for attempt in range(1, scans + 1):
            started = time.monotonic()
            report = await scanner.scan(url, timeout_ms=timeout_ms)
            elapsed = time.monotonic() - started
            durations.append(elapsed)

            used, processes = tree_memory_mb()
            peak = max(peak, used)
            print(
                f"{attempt:>4}  {elapsed:>8.2f}  {report['summary']['total']:>7}  "
                f"{used:>7.1f}  {used - previous:>+8.1f}  {processes}"
            )
            previous = used
    finally:
        await scanner.stop()

    settled, _ = tree_memory_mb()
    first, rest = durations[0], durations[1:]

    print(f"\nAfter the browser stops:   {settled:6.1f} MB")
    print(f"Peak during scanning:      {peak:6.1f} MB")
    print(f"Growth across {scans} scans:   {previous - after_launch:+6.1f} MB")
    print(f"\nFirst scan:  {first:.2f}s")
    if rest:
        print(f"Later scans: {sum(rest) / len(rest):.2f}s average, "
              f"{min(rest):.2f}s fastest, {max(rest):.2f}s slowest")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=FIXTURE.as_uri(),
        help="page to scan; defaults to the local broken.html fixture",
    )
    parser.add_argument("--scans", type=int, default=10)
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    args = parser.parse_args()

    return asyncio.run(run(args.url, args.scans, args.timeout_ms))


if __name__ == "__main__":
    raise SystemExit(main())
