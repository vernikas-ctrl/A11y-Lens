"""Task 10.1 -- build the container and prove a scan survives a memory cap.

Why this script exists
----------------------
Phase 1.2 measured a scan at 840MB on Windows and said so with a caveat it
could not remove: Windows accounts for memory differently from Linux, and
summing resident memory per process counts shared pages once per process. The
number was the right order of magnitude and nothing more.

A container with `-m` is the thing that settles it. The kernel enforces the
limit, it counts shared pages once, and when the total goes over, the OOM
killer ends the process. There is no arguing with the result: either the scan
finished or the container was killed.

This also reads the cgroup's own high-water mark from inside the container
once the scan is done, which is the number Phase 1.2 could never get -- not an
estimate of what a limit would see, but what the limit actually saw.

What it checks
--------------
1. The image builds at all, which is mostly a check that
   `playwright install --with-deps chromium` found every system library.
2. The server starts and answers /health inside the cap.
3. A real scan of a real page finishes without the container being killed.
4. The peak, as the kernel measured it.

Usage:
    python backend/scripts/container_check.py
    python backend/scripts/container_check.py --limit 512m
    python backend/scripts/container_check.py --url https://example.com

`--limit 512m` is worth running deliberately. The measurement in DECISIONS.md
predicts it dies, and a test that has never failed is a test nobody has
checked.
"""

import argparse
import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

IMAGE = "a11y-lens-backend:check"
CONTAINER = "a11y-lens-container-check"

# Not 8000: the dev backend is usually on it, and a check that quietly talked
# to a different server than the one it started would pass for the wrong
# reason.
HOST_PORT = 8099

# Heavy enough to be a real test. example.com would prove only that Chromium
# starts, which was task 1.1's job and was answered a fortnight ago.
DEFAULT_URL = "https://en.wikipedia.org/wiki/World_War_II"

HEALTH_TIMEOUT_S = 120
SCAN_TIMEOUT_S = 180

MB = 1024 * 1024


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def docker_available() -> bool:
    try:
        probe = run(["docker", "version", "--format", "{{.Server.Version}}"])
    except FileNotFoundError:
        return False
    return probe.returncode == 0


def build() -> bool:
    print("building " + IMAGE + " ... (the first run pulls Chromium)")
    # Streamed rather than captured: this is the slow step, and a build that
    # looks hung for four minutes is how somebody kills it and concludes the
    # whole thing is broken.
    completed = subprocess.run(["docker", "build", "-t", IMAGE, "."])
    if completed.returncode != 0:
        print("\nFAIL: the image did not build.", file=sys.stderr)
        print("If the failure names a missing shared library, the "
              "--with-deps line in the Dockerfile is where to look.",
              file=sys.stderr)
        return False
    return True


def start(limit: str, access_code: str) -> bool:
    run(["docker", "rm", "-f", CONTAINER])
    print("starting the container with a hard limit of " + limit + " ...")
    completed = run([
        "docker", "run", "-d", "--name", CONTAINER,
        # The cap itself. --memory-swap set equal to it stops the kernel from
        # using swap to paper over going past the limit, which would make this
        # pass here and still be killed on a swapless host.
        "-m", limit, "--memory-swap", limit,
        "-p", str(HOST_PORT) + ":8080",
        "-e", "ACCESS_CODE=" + access_code,
        # The placeholder is deliberate: explanations stay off, the scan still
        # runs, and no real key goes near a throwaway container. ENVIRONMENT
        # must stay development, because production refuses to start on a
        # placeholder key -- see config.py.
        "-e", "ANTHROPIC_API_KEY=paste-your-anthropic-api-key-here",
        "-e", "ENVIRONMENT=development",
        IMAGE,
    ])
    if completed.returncode != 0:
        print("FAIL: the container did not start.", file=sys.stderr)
        print(completed.stderr.strip(), file=sys.stderr)
        return False
    return True


def container_running() -> bool:
    out = run(["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER])
    return out.stdout.strip() == "true"


def was_oom_killed() -> bool:
    out = run(["docker", "inspect", "-f", "{{.State.OOMKilled}}", CONTAINER])
    return out.stdout.strip() == "true"


def peak_memory_mb():
    """The cgroup's own high-water mark, read from inside the container.

    This is the number Phase 1.2 could not get. cgroup v2 exposes it as
    memory.peak; the v1 name is kept as a fallback for older daemons.
    """
    for path in ("/sys/fs/cgroup/memory.peak",
                 "/sys/fs/cgroup/memory/memory.max_usage_in_bytes"):
        out = run(["docker", "exec", CONTAINER, "cat", path])
        if out.returncode == 0 and out.stdout.strip().isdigit():
            return int(out.stdout.strip()) / MB
    return None


def wait_for_health() -> bool:
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    started = time.monotonic()
    url = "http://127.0.0.1:" + str(HOST_PORT) + "/health"
    while time.monotonic() < deadline:
        if not container_running():
            print("FAIL: the container stopped before it served anything.",
                  file=sys.stderr)
            return False
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    waited = time.monotonic() - started
                    print("  /health answered after {:.1f}s".format(waited))
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(1)
    print("FAIL: /health never answered.", file=sys.stderr)
    return False


def scan(url: str, access_code: str):
    print("scanning " + url + " ...")
    request = urllib.request.Request(
        "http://127.0.0.1:" + str(HOST_PORT) + "/scan",
        data=json.dumps({"url": url}).encode(),
        headers={"Content-Type": "application/json",
                 "X-Access-Code": access_code},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=SCAN_TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print("  the server refused it: HTTP " + str(exc.code), file=sys.stderr)
        print("  " + exc.read()[:400].decode(errors="replace"), file=sys.stderr)
        return None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        # This is what being OOM-killed mid-scan looks like from out here: the
        # connection simply stops. Whether that is what happened is decided by
        # docker inspect below, not guessed from this.
        print("  the connection died: " + str(exc), file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the backend image and scan a page under a hard "
                    "memory cap.")
    parser.add_argument("--limit", default="2g",
                        help="hard memory cap, as docker -m takes it "
                             "(default: 2g, matching Cloud Run)")
    parser.add_argument("--url", default=DEFAULT_URL, help="the page to scan")
    parser.add_argument("--keep", action="store_true",
                        help="leave the container running afterwards")
    args = parser.parse_args()

    if not docker_available():
        print("Docker is not available on this machine.", file=sys.stderr)
        print("Install Docker Desktop, start it, and run this again. Until "
              "then task 10.1 is unverified -- and an unverified container is "
              "exactly what this task exists to prevent.", file=sys.stderr)
        return 2

    # Generated here, used by this one container, written nowhere. The real
    # access code has no business in a throwaway test.
    access_code = secrets.token_urlsafe(16)

    if not build():
        return 1

    try:
        if not start(args.limit, access_code):
            return 1

        if not wait_for_health():
            print("  OOM killed: " + str(was_oom_killed()), file=sys.stderr)
            print("  last log lines:", file=sys.stderr)
            print(run(["docker", "logs", "--tail", "20", CONTAINER]).stdout,
                  file=sys.stderr)
            return 1

        report = scan(args.url, access_code)
        killed = was_oom_killed()
        peak = peak_memory_mb() if container_running() else None

        print()
        print("=" * 62)
        print("limit           : " + args.limit)
        print("scan completed  : " + str(report is not None))
        if report is not None:
            summary = report.get("summary", {})
            print("issues found    : {} ({} critical)".format(
                summary.get("total"), summary.get("critical")))
        print("OOM killed      : " + str(killed))
        print("peak, as the kernel measured it: " + (
            "{:.0f} MB".format(peak) if peak is not None else "unavailable"))

        if killed or report is None:
            print("\nFAIL: a scan does not survive this limit.",
                  file=sys.stderr)
            return 1

        print("\nPASS: the scan finished inside the limit.")
        return 0
    finally:
        if not args.keep:
            run(["docker", "rm", "-f", CONTAINER])


if __name__ == "__main__":
    raise SystemExit(main())
