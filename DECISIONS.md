# Decisions

Why A11y-Lens is built the way it is. Newest last. Each entry records what was
decided, why, and what it costs — including the decisions that turned out to
have a downside, because those are the interesting ones.

---

## 2026-11-01 — Build it as a web app, not a browser extension

**Decided:** A web app where you enter a URL, with a Python backend that scans
the page.

**Why:** A browser extension was considered first and would have been simpler —
no server, no hosting, no running costs — because it can read the page you are
already on. It was rejected because an extension is awkward to share: a
reviewer would have to download the code and load an unpacked extension in
developer mode. A web app is a link.

**Cost:** A server is now required, which means hosting, cold starts, and
protecting against people feeding it malicious URLs. All of Phase 3 exists
because of this decision.

---

## 2026-11-01 — A11y-Lens is a portfolio piece

**Decided:** The primary audience is someone assessing my work; the secondary
audience is developers fixing their own site.

**Why:** It sets the priorities. A reviewer will click the link, look at the
interface, tab through it with the keyboard, read the README, and skim the
commit history. They will not read the scanner's internals.

**Cost:** Polish and a demo that always works outrank backend depth. Features
that would impress another engineer but that nobody can see — a job queue, a
plugin system — are not worth building here.

---

## 2026-11-01 — Live scanning sits behind a shared access code

**Decided:** The demo page is public. Entering a URL and running a real scan
requires an access code.

**Why:** Every scan spends Claude API credits, and the budget is zero. An open
endpoint is an open tap: one person with a loop could empty the account
overnight.

**Cost:** This is obscurity, not security — links get forwarded, pasted into
chat, and screenshotted. So it does not remove the need for a hard spend
ceiling; it only removes drive-by traffic from bots and crawlers. Both are
being built (Phase 6).

**Consequence:** A reviewer cannot run a live scan without being given the
code, which conflicts with this being a portfolio piece. Resolved by making
the public demo page (task 8.1) a real saved report that renders instantly with
no backend call, so the work is visible in one click.

---

## 2026-11-01 — One page per scan, but do not design against crawling

**Decided:** A scan covers a single URL. No following links, no multi-page
crawling.

**Why:** Crawling multiplies scan time, API cost and complexity, and needs a
job queue and a database. None of that is affordable on a zero budget, and none
of it makes the tool more impressive to look at.

**Cost:** Low, as long as the API response is shaped to describe *one page*
rather than assuming there is only ever one. Noted in the API contract.

---

## 2026-11-01 — Free hosting tiers only

**Decided:** Render free tier for the backend, Vercel free tier for the
frontend, and a hard ceiling on Claude API spend.

**Why:** The budget is zero. This is not a preference.

**Cost:** Three real consequences. The backend sleeps when idle, so the first
scan after a quiet period is slow or fails — handled by the demo page and task
10.5. The free instance has 512MB of memory, which may not be enough for a
full Chromium browser — which is why Phase 1 tests that before anything is
built on the assumption. And explanation caching stops being an optimisation
and becomes load-bearing.

---

## 2026-11-02 — Claude returns a corrected snippet, with its guesses marked

**Decided:** Each fix is a corrected code snippet, not a general description of
the rule. Alongside it, Claude must return an explicit list of the assumptions
it made.

**Why:** A corrected snippet is immediately usable; a general pattern leaves the
reader to do the last and hardest step. But for some rules Claude *cannot* know
the right answer — given an image with no `alt` text, it has no idea what the
image shows, so the snippet necessarily contains an invention.

**Cost:** More work in three places: the API contract carries an `assumptions`
list, the prompt has to instruct Claude to declare what it invented, and the UI
has to display those assumptions where someone will read them before copying.

**Why it is worth it:** Someone assessing this tool will immediately try to
catch it being confidently wrong. Visibly handling that is worth more than
pretending it cannot happen.

---

## 2026-11-02 — Dropped the one-branch-one-PR-per-task rule

**Decided:** Related tasks may share a branch and a pull request.

**Why:** `CLAUDE.md` originally required one PR per feature. For the Phase 0
documentation tasks that meant four pull requests containing four Markdown
files that only make sense read together.

**Cost:** Larger PRs are harder to review, and the git history no longer maps
one commit to one task. Still using separate commits per task to keep some of
that traceability.

**Note:** Pull requests are still never merged without approval.

---

## 2026-11-02 — Python 3.14, pinned in a .python-version file

**Decided:** The backend runs Python 3.14, not the 3.12 originally written in
`CLAUDE.md`. `CLAUDE.md` has been updated to match.

**Why:** 3.14 was the only version installed, and it is also Render's own
default for new services, so it needed no install and no deviation from the
host. Render supports any released version from 3.7.3 onward, so 3.12 was
equally available — it just had no advantage. Playwright 1.64.1 and greenlet
3.5.6 both installed cleanly on 3.14.

**Cost:** None found. The risk considered was that a new Python might lack
compiled wheels for Playwright's dependencies; it did not.

**The part that actually matters:** local and Render must run the *same*
version. A `.python-version` file at the repo root pins it, so Render cannot
silently pick something else later. "Works on my machine, fails on deploy" is
nearly always this.

---

## 2026-11-02 — A scan needs far more than 512MB, so the host is decided later

**Decided:** Task 1.2 no longer deploys to Render. Chromium's memory cost was
measured locally instead, and the choice of deploy host moves to Phase 10.
`CLAUDE.md` no longer names Render.

**The measurement.** `backend/scripts/memory_check.py` launches Chromium, loads
a heavy real page, injects axe-core 4.14.0, runs a full scan, and samples the
memory of every process in the tree every 100ms. Peak resident memory:

| Page | Everything loaded | Images, media and fonts blocked |
|---|---|---|
| Wikipedia, "World War II" | **859 MB** | 779 MB |
| The Guardian, front page | 536 MB | 528 MB |
| `example.com` (the floor) | 321 MB | 318 MB |

That last row is the one that kills 512MB outright. `example.com` is a heading
and one paragraph — there is no lighter real page — and it still costs 321MB,
because that is roughly what Chromium itself costs before any content. A 512MB
instance would have about 190MB of headroom for the actual page, and the
Guardian's front page alone needs more than that.

**Why:** 512MB was Render's number, not ours. The figure that matters — how
much a scan needs — is the same whoever hosts it, and measuring it locally
needs no hosting account, no credit card and no signup. Deferring the host
choice also means it gets made against a measured number instead of a hope.

**What this changes.** A 512MB instance was not marginal; it was wrong by a
factor of about 1.7. Had we built Phases 2–9 against that assumption and
discovered this at deploy time, the fix would have been a host migration with
the whole backend already written around the wrong constraint. **Phase 1 paid
for itself here.**

**The fallback, also measured.** `--lean` mode blocks images, media and fonts,
shrinks the viewport and waits only for `domcontentloaded`. It saved **80MB of
859** — nowhere near enough to reach 512MB. Lighter scan settings are therefore
*not* a viable fallback, and the fallback is a host with more memory. Worth
knowing before someone spends a day tuning Chromium flags.

**Lean mode is not free either.** Violations found on the Wikipedia article
went from 7 to 6 with resources blocked. Blocking fonts and images changes what
axe can see, so lean mode trades accuracy for memory. Stylesheets were left
loading on purpose, because `color-contrast` cannot be judged without them.
If lean mode is ever adopted, that accuracy loss needs its own measurement.

**Cost and honest limits of this number:**

1. **Measured on Windows.** Chromium divides work across processes differently
   on Linux, and resident memory is accounted differently. This is the right
   order of magnitude, not a verdict on a specific Linux box.
2. **Summing per-process RSS over-counts shared memory.** Pages shared between
   Chromium's processes are counted once per process, so the true figure a
   container limit would see is somewhat lower than 859MB. Lower — but not
   40% lower, which is what 512MB would require.
3. **Deliberately a worst case.** `wait_until="load"` plus a full axe run on one
   of the longest articles on the web. A typical page will cost less.
4. **Still unsettled:** whether it survives a hard container limit. That needs
   `docker run -m 512m`, and neither Docker nor WSL is installed on this
   machine. Task 10.1 builds a container anyway, so that is where it belongs.

**Hosts checked while deciding (re-verify in Phase 10; these change often):**
Render free web services spin down after 15 minutes idle and give 512MB —
likely too small. Fly.io has had no free tier for new accounts since Oct 2024.
Hugging Face Spaces offers free Docker hosting with far more memory, but
community reports say new accounts may get zero free CPU quota. Google Cloud
Run has a generous free tier but requires a card.

**Why deferring is safe:** Phases 2–9 are thirty tasks that run entirely on a
laptop, and task 8.1's demo page renders a saved report with the backend
switched off — so the public link works whether or not a backend is deployed.

---

## 2026-11-02 — Two error codes added to the API contract

**Decided:** `not_found` (404) and `method_not_allowed` (405) were added to the
error-code table in `docs/api-contract.md`, taking it from eight codes to ten.

**Why:** The original eight all describe ways a *scan* can fail. They do not
cover "you asked for a route that does not exist", which FastAPI answers by
itself in its own format — `{"detail": "Not Found"}`. Contract rule 1 says the
frontend branches on `error.code` and never on `error.message`, and that only
holds if every response a client can receive carries a code. Two formats would
mean two parsers in the frontend, and the second one would be the one with the
bug.

**Cost:** The contract is meant to be stable, and widening it two tasks after
writing it is not free. The alternative was worse: mapping a 404 onto one of
the scanning codes would have been a lie, and leaving FastAPI's shape in place
would have broken the rule the whole contract rests on. Recorded here because
`docs/api-contract.md` says the code is wrong until that file is *deliberately*
changed — this is the deliberate change.

**Also decided:** `detail` is `null` for unexpected failures. An exception
message can contain file paths, query fragments or key material, and an error
response goes to a stranger on the internet. The real cause is logged with a
short reference id that also appears in the response, so a user can quote it
and the log can be searched. A test asserts a planted fake key reaches the log
and not the response.

**And:** request logging records method, path, status and duration — never
headers, never the query string. The access code travels in a header, and the
quickest way to put a secret in a log file is to log all headers "just for
debugging" and never remove it.

---

## 2026-11-02 — localhost and 127.0.0.1 are different origins

**Decided:** `ALLOWED_ORIGINS` defaults to `http://localhost:5173` only, with
the trap documented in `backend/.env.example` rather than worked around by
listing both.

**Why:** Found while verifying task 2.4 in a real browser. The identical page,
served by the same server and calling the same API, succeeded from
`http://localhost:5173` and failed from `http://127.0.0.1:5173` — a browser
treats those as different origins. The failure surfaces as
`TypeError: Failed to fetch` with no explanation of which rule was broken.

**Cost:** Anyone who opens the frontend on `127.0.0.1` instead of `localhost`
hits a confusing error. Listing both would prevent that, but it would also
widen the production origin list by habit, and task 10.4 exists to narrow that
list to exactly one domain. A comment in `.env.example` seemed the better
trade: the person who hits this can fix it in five seconds once they know.

**Worth keeping in mind for Phase 10:** this is the same class of bug as
deploying with the Vercel preview URL missing from the list, where the symptom
is again an unexplained fetch failure rather than anything that names CORS.

---

## 2026-11-02 — The DNS-rebinding gap is documented, not closed

**Decided:** `check_url` resolves the hostname and refuses private addresses,
and that check is known to have a hole. The hole is written down here, narrowed
in two places, and deliberately not closed.

**The gap, plainly.** The safety check resolves the hostname and decides the
address is public. Playwright then opens the URL — and resolves the hostname
*again*. Two lookups, a moment apart. Someone who controls the DNS for their
own domain can answer the first lookup with a public address and the second
with `127.0.0.1`, and the browser connects somewhere the check never saw. It is
called **DNS rebinding**: the name stays the same, the address underneath it
moves. Setting a TTL of 0 makes the window between the two lookups as small as
the attacker likes.

**Why closing it properly is not a small job.** The real fix is to resolve the
name once and force the connection to *that exact address* — "pinning". With
Playwright that means routing the browser through a proxy we control or
intercepting at the socket level, and then keeping the original `Host` header
and SNI so TLS and virtual hosting still work. And that is only the top-level
page. A page can embed `<img src="http://169.254.169.254/latest/meta-data/">`,
and every sub-resource and every redirect does its own lookup, so pinning the
first URL alone would not be complete even once built.

**What is actually in place:**

1. **The check catches the realistic case.** Rebinding needs an attacker who
   owns a domain and runs a custom DNS server. Resolving the hostname already
   stops the thing people actually try — a typed private address, or a public
   name that simply points at a private one. `localtest.me` resolved to `::1`
   during this task, live.
2. **Phase 6's access code means it is not drive-by.** Scanning needs a shared
   code, so this cannot be found by a crawler. That is obscurity, not security,
   but it does change who could reach it.
3. **A follow-up with a real effect, in Phase 4.** Playwright's `page.route()`
   sees every request a page makes, so each one can be re-checked and aborted
   before it goes out. That covers sub-resources and redirects, which pinning
   the top-level URL would not, and it narrows the window to each individual
   request. It does not eliminate it — `route` sees the URL, not the address
   the browser is about to connect to.

**What it would cost an attacker who won the race.** Not much, and that is part
of why this is an acceptable risk here. The response carries axe-core's
findings and up to 500 characters of the offending element's HTML per issue —
so fragments of an internal page could leak, but not arbitrary file reads and
not whole responses. On AWS, the current metadata service also needs a `PUT`
with a token header, which a page navigation does not send; that is a genuine
second line of defence, but only on hosts that have it.

**Cost of this decision:** a known, written-down hole in a security control.
Accepted because the exposure is bounded, the realistic attack is already
blocked, and the proper fix is a proxy layer that would cost more than the rest
of Phase 3 put together. **If this app ever ran inside a network with anything
worth reaching, this decision would have to be revisited** — the reason it is
tolerable is that there is nothing interesting next to it.

---

## 2026-11-02 — axe-core lives in the repo, and the scanner is async

**Decided:** three things about how the scanner is built, all of which would
have been expensive to change later.

**1. axe-core 4.14.0 is committed to the repo** (`backend/app/vendor/axe-core/`,
652KB, MPL-2.0, licence included) rather than fetched from a CDN at scan time.
Phase 1's spike pulled it from jsdelivr, which is fine for a throwaway script
and wrong for the real thing: every scan would depend on someone else's server
being up at the moment a user clicks the button, and would spend part of its
time downloading 650KB that never changes. Vendoring also means the test suite
runs with no internet. *Cost:* updating axe is now a manual act. That is
arguably the point — an axe update changes what the scanner finds, so it should
be a decision with a test run attached, not something that happens silently
between two scans.

**2. The scanner is written against Playwright's async API.** Playwright's
synchronous API cannot be called from inside a running event loop, which is
exactly what FastAPI is. Task 4.6 puts one browser behind the whole server, so
the browser has to live in the server's own loop. Writing it synchronously now
would mean rewriting every line of it at 4.6. *Cost:* the code is denser to
read, so it carries more comment than it otherwise would.

**3. The scanner does not check its own URLs.** `app.url_safety` is applied by
the endpoint (task 4.7), not by `app.scanner`. This looks like a hole and is
not: `check_url` refuses `file://` and private addresses, correctly, and the
test fixture is a local file — so a scanner that policed its own input could
never be tested against a page we control, and the tests would have to point at
a real website that can be redesigned without warning. Enforcing the check
once, at the front door, keeps it in one place and keeps the scanner testable.
*Cost:* a future second caller of the scanner could forget the check. Guarded
by a test on the endpoint asserting the check is applied there.

---

## 2026-11-02 — The fixture carries a fault the scanner cannot see

**Decided:** `backend/tests/fixtures/broken.html` contains a seventh fault that
axe-core does not report, documented as a blind spot, with a test asserting it
stays unreported.

**How it was found.** The fixture was built with six planted faults and the
first scan found five. The missing one was the unlabelled form field — and the
reason was not a scanner bug. The field had `placeholder="Search"` and nothing
else, and **axe-core treats a placeholder as a valid accessible name and passes
the rule outright.** Not a warning, not an "incomplete" result: a clean pass,
confirmed by querying axe about that one element directly.

axe is right about the specification and wrong about the person. Placeholder
text disappears the instant someone starts typing, so anyone who pauses
mid-form has lost the only thing that said what the box was for — and its
usual grey-on-white styling tends to fail contrast as well.

**Why it stayed in.** The README and the empty-results screen (task 8.9) both
claim automated tools catch roughly a third of real accessibility problems.
This page can now *demonstrate* that instead of only asserting it, with a
concrete example, on the one page a reviewer is most likely to read.

**Cost:** a test that asserts something is *not* found, which is a shape of
test that usually ages badly. Accepted because it is the only way the gap stays
honest: if a future axe-core starts catching it, the test fails and says so,
rather than the blind spot quietly closing while the README keeps claiming it.

**The first instinct was that the scanner was broken.** Worth recording, because
it is the same instinct that would have led to deleting the planted fault and
never finding out why.

---

## 2026-11-02 — One browser for the whole server, and a "Done when" that was wrong

**Decided:** Chromium is launched once, when the app starts, and every scan
gets a fresh *context* inside it rather than a fresh browser.

**Why.** Phase 1 measured Chromium's floor at about 321MB and several seconds
for a page consisting of one heading. That is a cost that only needs paying
once. Launching per request would also mean two browsers alive at the same
moment whenever two requests overlap, which on a memory-limited host is how a
process gets killed rather than merely slowed.

A context is Playwright's word for a private browser profile: its own cookies,
storage and cache. One per scan means two scans cannot see each other, which
matters because the URLs come from strangers. The context is closed in a
`finally`, so a failed scan releases its memory too.

**The measurement, from `backend/scripts/scan_loop_check.py`, ten scans of
`example.com`:**

| | |
|---|---|
| Browser launched, before any scan | 212 MB |
| After the first scan | 331 MB |
| Oscillating across scans 2–10 | 358–412 MB, no trend |
| Peak | 412 MB |
| After the browser stops | 65 MB |
| Chromium processes | 6, unchanged throughout |

Memory rises once as caches fill and then moves up and down without climbing.
A leak looks like roughly the same increase on every scan; this does not.

**Task 4.6's stated "Done when" was wrong, and the measurement is what showed
it.** It asked for the second scan to be measurably faster than the first. It
is not: on an already-running browser the first scan took 0.84s and later
scans averaged 0.75s, which is noise. The saving from reuse is **the browser
launch**, which the first scan does not pay for either, because the app
launched it at startup.

So the test asserts the two things that are actually true and actually exact:
the browser object is the same one for every scan (which fails immediately if
reuse is removed — checked by removing it), and a warm scan costs less than
starting a browser and scanning. The timing numbers live in the script, which
prints them for a person to judge, rather than in a test that would invent a
threshold and fail on a busy laptop.

**Cost:** the browser is started eagerly at app startup, so the server takes
about a second longer to become ready. Deliberate: the alternative is the
first user paying for it on top of their own scan, and on a free tier that
sleeps, that user is arriving at the worst possible moment anyway.

---

## 2026-11-02 — Every failure a scan can have, named

**Decided:** the mapping from "something went wrong" to the contract's error
codes, settled once in `app/scanner.py` rather than per call site.

| What happened | Code | Status |
|---|---|---|
| Page never finished loading | `scan_timeout` | 504 |
| axe itself did not finish in time | `scan_timeout` | 504 |
| `net::ERR_TIMED_OUT`, `ERR_CONNECTION_TIMED_OUT` | `scan_timeout` | 504 |
| Any other `net::` failure — no such domain, refused, bad certificate, redirect loop | `unreachable` | 502 |
| Target returned 4xx or 5xx | `unreachable` | 502 |

**Two judgement calls worth writing down.**

A connection that *times out* is reported as a timeout and not as an
unreachable host, even though both mean "no page". The person reading the
message has to decide whether to try again, and those two answers differ.

A target returning 404 or 500 is `unreachable`, which is arguable — an error
page is still a page, and scanning it would produce findings. But someone who
typed a URL expecting a page has not got one, and reporting on the
accessibility of the error page answers a question they did not ask.
`docs/api-contract.md` already settled this; the code follows it.

**Nothing from the exception reaches the user.** Chromium's error text can
carry local file paths, and these responses go to strangers. `detail` says
what happened in plain words; the code is what the frontend branches on. There
is a test that plants a Windows path in an error message and asserts it does
not come back.

**Also built here: the DNS-rebinding mitigation promised in Phase 3.** Every
request the page makes — not just the URL that was typed — is re-checked, and
aborted if it points somewhere private. That covers an embedded
`<img src="http://169.254.169.254/latest/meta-data/">` and covers redirects,
neither of which `check_url` can see. A blocked request is aborted rather than
failing the scan: one blocked image should not lose the whole report.

**Worth knowing for Phase 10:** the browser announces itself as headless
Chrome. Some sites serve a challenge page or a block to headless browsers,
which would arrive here as `unreachable` with nothing explaining why. Not hit
yet, not worked around, and worth remembering when the first real-world scan
fails for no visible reason.
