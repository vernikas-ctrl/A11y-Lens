"""Task 1.1 — prove Playwright can drive a real browser on this machine.

A throwaway diagnostic, not part of the app. Phase 1 exists to answer one
question before the rest of the backend depends on the answer: can we actually
run a full Chromium? Task 1.2 asks the same question on Render's 512MB free
tier, where the answer is much less certain.

Usage:
    backend/.venv/Scripts/python.exe backend/scripts/browser_check.py [url]
"""

import sys
import time

from playwright.sync_api import sync_playwright

DEFAULT_URL = "https://example.com"


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    started = time.monotonic()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            # domcontentloaded, not the default "load": we only need the DOM,
            # and waiting on every image and font makes slow pages look broken.
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            title = page.title()
            final_url = page.url
        finally:
            browser.close()

    print(f"requested : {url}")
    print(f"final url : {final_url}")
    print(f"title     : {title!r}")
    print(f"elapsed   : {round((time.monotonic() - started) * 1000)} ms")

    if not title:
        print("\nFAIL: the page returned an empty title.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
