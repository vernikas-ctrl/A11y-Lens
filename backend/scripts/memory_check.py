"""Task 1.2 — measure how much memory one real scan actually needs.

Why this script exists
----------------------
Phase 1 answers one question before the rest of the backend depends on it: how
much memory does a Playwright scan need? Task 1.1 proved Chromium runs at all.
This measures what running it costs.

The original plan was to answer this by deploying to Render's 512MB free tier.
We dropped that. 512MB was Render's number, not ours, and the figure that
actually matters -- how much a scan needs -- is the same whoever hosts it.
Measuring locally needs no hosting account, so the deploy host can be chosen in
Phase 10 against a number we already have.

What it measures, and why
-------------------------
Peak resident memory of this process's entire descendant tree, not Chromium
alone. A Linux container counts every process in its cgroup against the memory
limit, and Playwright runs a Node driver process alongside the browser, so the
tree total is what a container limit would compare against. Chromium's own
share is reported separately, because that is the part that grows with page
weight.

Each page is loaded with wait_until="load" and then scanned with axe-core, so
the result is a deliberate worst case. The real backend will use
"domcontentloaded", which waits for less.

The honest caveat
-----------------
This runs on Windows, where Chromium divides work across processes differently
than on Linux and where resident memory is accounted differently. Treat the
result as the right order of magnitude, not as proof about any particular 512MB
Linux box. A definitive answer needs `docker run -m 512m`, which belongs to
task 10.1.

Two modes
---------
Default mode is the worst case described above. `--lean` applies the savings
the real backend can plausibly adopt -- a small viewport, "domcontentloaded",
and refusing to download images, media and fonts -- so the cost of the fallback
is measured rather than guessed. Blocking images does not blind axe-core: the
`<img>` elements and their attributes are still in the DOM, so rules like
`image-alt` are unaffected. Stylesheets are deliberately still allowed, because
`color-contrast` cannot be judged without them.

Usage:
    backend/.venv/Scripts/python.exe backend/scripts/memory_check.py
    backend/.venv/Scripts/python.exe backend/scripts/memory_check.py --lean
    backend/.venv/Scripts/python.exe backend/scripts/memory_check.py <url> ...
"""

import sys
import threading
import time

import psutil
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

# Pinned, not "latest": a silent version bump would change both the measurement
# and the violation count without anything in this file changing.
AXE_CDN = "https://cdn.jsdelivr.net/npm/axe-core@4.14.0/axe.min.js"

# Two genuinely heavy real pages: a very long article with hundreds of images,
# and an ad-and-script-heavy news front page. Toy pages would flatter us.
DEFAULT_PAGES = [
    "https://en.wikipedia.org/wiki/World_War_II",
    "https://www.theguardian.com/international",
]

SAMPLE_INTERVAL_S = 0.1
BROWSER_NAME_HINTS = ("chrome", "chromium", "headless_shell")

MB = 1024 * 1024

# Decoded images are usually the single largest cost on an image-heavy page.
# Stylesheets are NOT here: color-contrast needs them.
LEAN_BLOCKED_RESOURCES = ("image", "media", "font")


class TreeSampler(threading.Thread):
    """Polls the memory of every child process until told to stop.

    Sampling rather than reading one final number: the peak is what a container
    limit kills you for, and it can occur in the middle of a page load and be
    gone a second later.
    """

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self._root = psutil.Process()
        self._stop = threading.Event()
        self.peak_tree_mb = 0.0
        self.peak_browser_mb = 0.0
        self.peak_process_count = 0
        self.samples = 0

    def run(self) -> None:
        while True:
            tree_bytes = 0
            browser_bytes = 0
            count = 0
            for proc in self._root.children(recursive=True):
                try:
                    rss = proc.memory_info().rss
                    name = proc.name().lower()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # Chromium starts and stops helper processes constantly;
                    # one vanishing mid-sample is normal, not an error.
                    continue
                tree_bytes += rss
                count += 1
                if any(hint in name for hint in BROWSER_NAME_HINTS):
                    browser_bytes += rss

            self.peak_tree_mb = max(self.peak_tree_mb, tree_bytes / MB)
            self.peak_browser_mb = max(self.peak_browser_mb, browser_bytes / MB)
            self.peak_process_count = max(self.peak_process_count, count)
            self.samples += 1

            if self._stop.wait(SAMPLE_INTERVAL_S):
                return

    def stop(self) -> None:
        self._stop.set()
        self.join(timeout=5)


def measure_page(url: str, lean: bool = False) -> dict:
    """Launch a browser, load one page, run axe over it, report the peak."""
    sampler = TreeSampler()
    sampler.start()
    started = time.monotonic()
    result = {"url": url, "title": "", "axe_ran": False,
              "violations": None, "error": None, "lean": lean}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                if lean:
                    # A smaller viewport means fewer pixels to composite, which
                    # is real memory. 1280x800 still counts as a desktop
                    # layout, so responsive breakpoints behave normally.
                    page = browser.new_page(
                        viewport={"width": 1280, "height": 800})
                    page.route(
                        "**/*",
                        lambda route: (
                            route.abort()
                            if route.request.resource_type
                            in LEAN_BLOCKED_RESOURCES
                            else route.continue_()
                        ),
                    )
                else:
                    page = browser.new_page()

                page.set_default_timeout(90_000)
                page.goto(
                    url,
                    wait_until="domcontentloaded" if lean else "load",
                    timeout=90_000,
                )
                result["title"] = page.title()

                # axe runs inside the page, so its own code and its results
                # object both count towards the browser's memory. Leaving it
                # out would under-report a real scan by whatever axe costs.
                try:
                    page.add_script_tag(url=AXE_CDN)
                    result["violations"] = page.evaluate(
                        "async () => (await axe.run()).violations.length"
                    )
                    result["axe_ran"] = True
                except PlaywrightError as exc:
                    first_line = exc.message.splitlines()[0]
                    result["error"] = "axe step failed: " + first_line
            finally:
                browser.close()
    except PlaywrightError as exc:
        result["error"] = exc.message.splitlines()[0]
    finally:
        sampler.stop()

    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    result["peak_tree_mb"] = round(sampler.peak_tree_mb, 1)
    result["peak_browser_mb"] = round(sampler.peak_browser_mb, 1)
    result["peak_processes"] = sampler.peak_process_count
    result["samples"] = sampler.samples
    return result


def main() -> int:
    args = sys.argv[1:]
    lean = "--lean" in args
    urls = [a for a in args if not a.startswith("--")] or DEFAULT_PAGES
    results = []

    print("mode: " + ("lean (images, media and fonts blocked)"
                      if lean else "worst case (everything loaded)"))
    print()

    for url in urls:
        print("measuring " + url + " ...", flush=True)
        r = measure_page(url, lean=lean)
        results.append(r)
        if r["error"]:
            print("  WARNING: " + r["error"])
        print("  title            : {!r}".format(r["title"]))
        print("  axe ran          : {}  violations={}".format(
            r["axe_ran"], r["violations"]))
        print("  peak whole tree  : {} MB".format(r["peak_tree_mb"]))
        print("  peak browser only: {} MB".format(r["peak_browser_mb"]))
        print("  peak processes   : {}".format(r["peak_processes"]))
        print("  elapsed          : {} ms ({} samples)".format(
            r["elapsed_ms"], r["samples"]))
        print()

    worst = max(results, key=lambda r: r["peak_tree_mb"])
    print("=" * 62)
    print("WORST CASE: {} MB total tree ({} MB browser) on {}".format(
        worst["peak_tree_mb"], worst["peak_browser_mb"], worst["url"]))
    print("Windows measurement. Indicative of the order of magnitude only;")
    print("a 512MB Linux container is settled definitively in task 10.1.")

    # Only a hard failure to drive the browser fails this task. A large number
    # is a finding, not an error.
    if all(r["error"] and not r["axe_ran"] for r in results):
        print("\nFAIL: no page could be measured.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
