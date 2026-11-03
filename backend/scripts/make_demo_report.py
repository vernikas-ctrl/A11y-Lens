"""Produce the demo report the frontend ships. Task 8.1.

    cd backend
    .venv/Scripts/python scripts/make_demo_report.py

Writes `frontend/src/demo/report.json`.

**The findings are real.** This serves `tests/fixtures/broken.html` over
local HTTP and runs the actual scanner against it -- same Playwright, same
axe-core, same code path as a live scan. What comes out is genuine axe-core
output, not something typed by hand to look plausible.

**The explanations are not.** They are written by hand, because there is no
API budget, and the frontend labels them as hand-written wherever they are
shown. See DECISIONS.md.

WHY THE LOCAL FIXTURE rather than a real website: a demo report of somebody
else's site ships their mistakes as our marketing, and it changes the day
they fix it. `broken.html` has six planted faults that do not move, each
documented in the file, plus one deliberate blind spot the scanner cannot
see -- which is worth showing in a demo rather than hiding.

WHY file:// RATHER THAN A LOCAL WEB SERVER: the first attempt served the
fixture over http://127.0.0.1 and the scan failed -- correctly. The scanner
re-checks every request the page makes against the private-address rules, so
a loopback address is refused at the browser level as well as at the
endpoint. `file://` is the route `tests/test_scanner.py` already uses, and
the one the blocker deliberately lets through: non-http schemes go nowhere
near the network. Nothing is being bypassed or weakened.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.scanner import Scanner  # noqa: E402

FIXTURE = BACKEND / "tests" / "fixtures" / "broken.html"
OUT = BACKEND.parent / "frontend" / "src" / "demo" / "report.json"
TIMEOUT_MS = 30_000


async def main() -> int:
    if not FIXTURE.is_file():
        print(f"fixture missing: {FIXTURE}", file=sys.stderr)
        return 1

    url = FIXTURE.as_uri()
    print(f"scanning {url}")

    scanner = Scanner()
    await scanner.start()
    try:
        report = await scanner.scan(url, TIMEOUT_MS)
    finally:
        await scanner.stop()

    # The URL is replaced with something a reader can make sense of. A demo
    # report claiming to have scanned 127.0.0.1 on a random port would be
    # confusing, and the port changes every run, which would make this file
    # churn in git for no reason.
    report["url"] = "https://example.com/a-deliberately-broken-page"

    issues = report["issues"]
    print(f"\n{len(issues)} findings:")
    for issue in issues:
        print(f"  {issue['severity']:9} {issue['rule_id']:20} {issue['selector']}")

    counts = report["summary"]
    print(f"\nsummary: {counts}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(BACKEND.parent)}")
    print("\nExplanations are null. add_demo_explanations.py fills them in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
