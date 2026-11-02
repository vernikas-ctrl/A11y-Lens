# A11y-Lens — Task Breakdown

Web app: you enter a URL → the backend loads that page with Playwright and
scans it with axe-core → the Claude API explains each issue in plain language
and suggests a corrected code snippet → the frontend shows the report.

**Stack** (from `CLAUDE.md`): `frontend/` React + TypeScript + Tailwind + Vite
on Vercel. `backend/` Python 3.14 + FastAPI + Playwright, on a host chosen in
Phase 10.

---

## Decisions this plan is built on

Agreed 1–2 Nov 2026. If one of these changes, the affected phase changes with it.

| | Decision | What it drives |
|---|---|---|
| **Purpose** | A portfolio piece | Polish, a demo that always works, and visible reasoning matter more than deep backend features |
| **Audience** | Developers fixing their own site | Explanations lead with the code fix, not the theory |
| **Access** | Public demo page; live scanning behind a shared access code | Phase 6. Obscurity, not security — the spend cap stays regardless |
| **Scan scope** | One page per scan; don't block crawling later | Response shape describes one page, so a second can be added without breaking it |
| **Budget** | Strictly free tiers, hard zero | Caching and a daily API ceiling are load-bearing, not optimisations |
| **Fix format** | Corrected snippet, with guessed parts clearly marked | Phases 0.5, 5 and 8 all depend on this shape |

**Not in v1:** user accounts, saved scan history, shareable report links,
multi-page crawling, downloadable reports, and any database at all. Each of
those needs storage this app deliberately doesn't have. Adding a Markdown
download later is roughly one task; adding history is four or five.

---

## How to use this file

- One task per sitting. Each is sized for **about an hour or less**.
- Tick a box only when its **Done when** line is literally true — you've *seen*
  it work, not just written the code.
- Tasks run in order. Each phase assumes the ones before it are finished.
- Per `CLAUDE.md`: one branch and one PR per task, tests before "done", and a
  5-bullet explanation plus any real decision written into `DECISIONS.md`.

**Jargon, once:**
- **axe-core** — the industry-standard accessibility testing engine. It does
  the rule-checking so you don't write 90 rules by hand.
- **Playwright** — software that drives a real browser from Python. Needed
  because many sites build their content with JavaScript; plain HTML fetching
  would see an empty shell.
- **SSRF** (Server-Side Request Forgery) — when someone gives your server a URL
  pointing *back into your own private network* (`localhost`,
  `169.254.169.254`) so your server fetches secrets and hands them over. Your
  app takes URLs from other people, so this is real, not theoretical.
- **Spike** — a short throwaway experiment to answer one risky question before
  you build on the answer.

---

## Phase 0 — Decisions and the shared contract

- [x] **0.1 Create the repo skeleton** — `frontend/` and `backend/` folders, a
  root `.gitignore` (Python `__pycache__`, `.venv`, `node_modules`, `.env`,
  `dist`), and a `README.md` with the one-paragraph description. ~30 min
  **Done when:** `git status` is clean and `.env` is proven ignored — create a
  dummy one and confirm git does not offer to commit it.

- [x] **0.2 Start DECISIONS.md** — seed it with the six decisions in the table
  above, one dated entry each: what was decided, and *why*. For a portfolio
  piece this file is evidence, not admin — a reviewer reading your reasoning
  learns more about you than the feature list does. ~30 min
  **Done when:** `DECISIONS.md` has six dated entries, each with a stated
  reason.

- [x] **0.3 Write down what "finished" means** — in `README.md` or
  `docs/scope.md`: who it's for, and the checkable list of what v1 must do.
  Also the three things it deliberately won't do. Scope you haven't written
  down is scope that grows. ~30 min
  **Done when:** the file states the audience in one sentence and lists at
  least six checkable conditions for v1 being done.

- [x] **0.4 Practise the branch-and-PR loop once** — on a trivial change (a
  README typo): branch, commit, push, open a PR, then **stop without merging**.
  Learn the workflow on something harmless. ~30 min
  **Done when:** an open PR exists on GitHub that you have deliberately not
  merged.

- [x] **0.5 Write the API contract** — in `docs/api-contract.md`, by hand, no
  code. The request (`{ "url": "..." }`) and the exact response. Per issue:
  rule id, severity, element selector, the offending HTML, the plain-language
  explanation, **the corrected snippet**, and **a list of the assumptions
  Claude made** so the UI can mark guessed parts. Note explicitly that a
  response describes **one page**, so a future version can add more without
  breaking the shape. ~1 hr
  **Done when:** you could hand this file to two strangers and they could build
  the two halves without speaking to each other.

---

## Phase 1 — Prove the risky part first

Playwright drives a full Chromium browser, which wants a lot of memory once a
real page is loaded. How much was the single biggest unvalidated assumption in
this plan, and everything from Phase 2 onwards is built on the answer. Finding
out now costs an hour; finding out in Phase 10 costs a rebuild.

**Both tasks are done, and the answer was not the expected one.** A scan of a
heavy page peaks near **859MB** — not the 300–500MB assumed, and well over the
512MB a free tier typically offers. Lighter scan settings recover only 80MB of
that, so the fallback is a bigger host, not a tuned browser. Full numbers and
method in `DECISIONS.md`.

- [x] **1.1 Launch a browser locally** — a standalone script: open headless
  Chromium, visit a URL, print the page title. ~45 min
  **Done when:** running the script prints the real title of `example.com`.

- [x] **1.2 Measure what a scan actually costs in memory** — a script that
  launches Chromium, loads a heavy real page, runs a full axe-core scan over
  it, and samples the whole process tree's memory to report the peak. Runs
  locally, so it needs no hosting account, no card and no signup. A second
  `--lean` mode measures the cost of the obvious savings rather than guessing
  at them. ~1 hr
  **Done when:** `DECISIONS.md` records the measured peak memory, whether it
  fits a 512MB tier, and — since it doesn't — which fallback you're taking
  (lighter scan settings, a different host, or a paid tier).
  *Originally "deploy a spike to Render's free tier". Rewritten because the
  useful number is how much a scan needs, which is the same whoever hosts it —
  and measuring it locally unblocked the whole phase without an account.*

---

## Phase 2 — Backend skeleton

- [x] **2.1 Python 3.14 environment and FastAPI** — virtual environment,
  `requirements.txt`, FastAPI + uvicorn, and `GET /health` returning
  `{"status": "ok"}`. ~45 min
  **Done when:** `uvicorn` runs locally and `localhost:8000/health` returns
  that JSON in your browser.
  *Returns `{"status": "ok", "version": "0.1.0"}` — the version field comes
  from `docs/api-contract.md`, which outranks the summary written here.
  Requirements are split into `requirements.txt` (what a deploy installs) and
  `requirements-dev.txt` (tests and diagnostics).*

- [x] **2.2 Set up pytest and test /health** — the harness plus the first real
  test. Second, not last: every later "Done when" leans on being able to run
  tests, and retrofitting a harness onto finished code is miserable. ~45 min
  **Done when:** `pytest` runs from a clean terminal and reports 1 passed.
  *4 passed. Run with `cd backend && .venv/Scripts/python.exe -m pytest`.*

- [x] **2.3 Configuration from .env** — settings (API key, access code,
  allowed origins, timeouts, daily spend cap) read from environment variables,
  with a committed `.env.example` listing every key and **no real values**.
  ~45 min
  **Done when:** the app starts with your `.env`, fails with a clear message
  when a required key is missing, and `.env.example` lists every key used.
  *All three verified. Secrets are `SecretStr`, so printing or logging a
  settings object shows `**********`. Two tests compare `.env.example` against
  the settings class in both directions, so documentation drift fails the
  build rather than surfacing at deploy time.*

- [x] **2.4 Enable CORS** — browsers block a page on one domain from calling an
  API on another unless the API allows it. Read allowed origins from config,
  never hard-coded. ~30 min
  **Done when:** a `fetch()` from `localhost:5173` to `localhost:8000`
  succeeds with no CORS error in the browser console.
  *Verified in a real browser, both ways: the fetch succeeds from
  `localhost:5173` and the same page is refused from `127.0.0.1:5173`, which
  is a different origin. `X-Access-Code` is in `allow_headers`, so Phase 6's
  preflight will work.*

- [x] **2.5 One error shape everywhere** — matching the contract from 0.5,
  applied to every failure, plus request logging. ~45 min
  **Done when:** requesting a route that doesn't exist returns your error
  shape, not FastAPI's default.
  *404 and 405 both return `{"error": {...}}` over real HTTP. Needed two new
  contract codes (`not_found`, `method_not_allowed`) — see `DECISIONS.md`.
  Unexpected failures return `detail: null` plus a reference id that also
  appears in the server log.*

---

## Phase 3 — URL safety (before anything fetches a URL)

- [x] **3.1 Validate the URL's shape** — scheme must be `http` or `https`,
  must have a hostname; reject everything else. ~45 min
  **Done when:** empty, `file:///etc/passwd`, `not a url` and
  `javascript:alert(1)` all return your "invalid URL" error.
  *All four verified over real HTTP. Schemes are an allow-list, so anything
  not yet thought of is refused by default. Also refuses credentials in the
  URL: `http://expected.com@evil.example/` connects to `evil.example` while a
  human reads `expected.com`.*

- [x] **3.2 Block private and internal addresses** — resolve the hostname to an
  IP, then reject loopback (`127.0.0.1`, `::1`), private ranges (`10.x`,
  `192.168.x`, `172.16–31.x`), link-local (`169.254.x`, which covers the cloud
  metadata address) and reserved ranges. **Resolve the name rather than
  pattern-matching the text** — `localtest.me` is a public name pointing at
  `127.0.0.1`. ~1 hr
  **Done when:** `http://localhost:8000/health`, `http://169.254.169.254/` and
  `http://10.0.0.1/` are each refused with a "blocked address" error.
  *All three verified over real HTTP, and `localtest.me` really did resolve to
  `::1`. Every address a name answers with is checked, not just the first.
  Needed two separate rules: `100.64.0.0/10` (carrier-grade NAT) is not
  `is_private` on this Python, and multicast `224.0.0.1` reports as globally
  reachable — either check alone lets one of them through.*

- [x] **3.3 Tests for the SSRF rules** — one parametrised test covering every
  case from 3.1 and 3.2, blocked and allowed. The suite you'll be gladdest to
  have. ~45 min
  **Done when:** `pytest` covers at least 12 URL cases and all pass.
  *54 cases; 92 tests in the suite overall. The hostname cases use an injected
  resolver so they never depend on the internet. Confirmed the tests bite by
  breaking the code four ways and checking each break failed the test written
  for it.*

- [x] **3.4 Note the DNS-rebinding gap** — a hostname can pass your check and
  resolve to a private IP microseconds later, when the browser actually
  connects. Fully closing it is out of scope; write the gap and your chosen
  mitigation into `DECISIONS.md`. For a portfolio piece, a documented known
  limitation reads as competence. ~30 min
  **Done when:** `DECISIONS.md` explains the gap in your own words and names
  what you chose to do about it.
  *Written down and accepted, with the one mitigation that has a real effect
  pushed into task 4.7.*

---

## Phase 4 — The scanning engine

- [ ] **4.1 Build a deliberately broken test page** —
  `backend/tests/fixtures/broken.html` with one of each: image with no `alt`,
  input with no label, skipped heading level, icon-only button, low-contrast
  text, missing `lang`. Comment each. A local file means your tests never
  depend on the internet or on someone else's site changing. ~45 min
  **Done when:** you can open it in a browser and count every planted issue by
  eye.

- [ ] **4.2 Run axe-core inside the page** — inject axe into the loaded page,
  run it, dump the raw JSON to a file and read it once. ~1 hr
  **Done when:** scanning `broken.html` produces a JSON file of violations
  that you have read through.

- [ ] **4.3 Normalise axe output into your contract** — map axe's raw result to
  the per-issue shape from 0.5, keeping only the fields you promised. ~1 hr
  **Done when:** the scan function returns objects matching
  `docs/api-contract.md` exactly, with no leftover axe-specific fields.

- [ ] **4.4 Timeouts and failure handling** — a page that never loads, a 404, a
  redirect loop, a 20-second page, a domain that doesn't exist. Each gives a
  clear error, never a hang. ~1 hr
  **Done when:** scanning `https://this-domain-does-not-exist-9z8y.com`
  returns a readable error within your timeout.

- [ ] **4.5 Tests for the scanner** — scan the local fixture, assert the known
  issues are found. Assert on **rule ids, not counts** — counts change when axe
  updates and you'd get mystery failures. ~45 min
  **Done when:** `pytest` asserts at least four specific rule ids from
  `broken.html` and passes.

- [ ] **4.6 Reuse the browser between scans** — launching Chromium per request
  is slow and, on 512MB, risky. Start it once with the app, give each scan a
  fresh isolated context, shut down cleanly. ~1 hr
  **Done when:** the second scan is measurably faster than the first, and ten
  scans in a row don't grow memory without bound.

- [ ] **4.7 Wire up POST /scan** — validate the URL (Phase 3), scan it, return
  the normalised result. No Claude yet. ~45 min
  **Done when:** posting `{"url": "https://example.com"}` returns real
  violations, and `{"url": "http://localhost"}` returns the blocked error.
  **Also re-check every request the page makes** via Playwright's
  `page.route()`, aborting any that points somewhere private. Task 3.1's check
  only sees the URL you typed, so a page embedding
  `<img src="http://169.254.169.254/latest/meta-data/">` would sail past it —
  and this is the narrowing named in the DNS-rebinding entry in
  `DECISIONS.md`. Add a test that a page requesting a private address has that
  request blocked.

---

## Phase 5 — Claude explanations

Anthropic Python SDK (`anthropic`), model `claude-opus-5-5`. **The API key
lives only in `.env`.** Every call costs real money against a zero budget, so
these are ordered to keep spend near nothing until it works.

- [ ] **5.1 One hello-world API call** — a throwaway script sending one short
  message, key read from `.env`. ~45 min
  **Done when:** it prints a response, and `git grep` for your key returns
  nothing.

- [ ] **5.2 Design the prompt on paper first** — in `docs/prompt.md`: the
  system prompt (what a good explanation contains, who's reading it, the WCAG
  criterion to cite, **and the instruction to list every assumption it made**),
  plus exactly which fields of one violation you send. Writing it down before
  coding is what makes it improvable later. ~1 hr
  **Done when:** `docs/prompt.md` holds the full system prompt text and one
  worked example of the input.

- [ ] **5.3 Explain one violation as structured JSON** — use structured output
  (`output_config.format` with your JSON schema, via `client.messages.parse()`)
  so the reply is schema-valid every time, rather than hoping for clean JSON.
  The schema must carry the corrected snippet **and** the assumptions list.
  ~1 hr
  **Done when:** one real violation returns a parsed object with explanation,
  snippet and assumptions filled in, and no hand-rolled JSON parsing anywhere
  in the path.

- [ ] **5.4 Make the guesses honest** — for an image with no `alt`, Claude
  cannot know what the image shows, so the snippet contains an invention. The
  assumptions list must name it ("assumed this image is the company logo") so
  the UI can mark it. A reviewer *will* try to catch the tool being confidently
  wrong; visibly handling that is worth more than pretending it can't happen.
  ~1 hr
  **Done when:** a missing-`alt` violation returns a snippet plus at least one
  explicit assumption naming what it invented.

- [ ] **5.5 Handle API failures properly** — catch specific exceptions
  most-specific-first (not found → rate limited → other API status →
  connection error), and always check `stop_reason` before reading content.
  ~45 min
  **Done when:** a deliberately wrong API key produces your clear error, not a
  stack trace.

- [ ] **5.6 Degrade gracefully when Claude is unavailable** — if explanation
  fails, still return the axe results with explanations marked unavailable. A
  partial report beats a failed one, and this is also what the app does once
  the daily cap is hit. ~45 min
  **Done when:** with the API key blanked out, `POST /scan` still returns
  violations and the response still matches the contract.

- [ ] **5.7 Explain a whole page in one pass** — one call for all issues rather
  than one per issue: far cheaper and faster. Mind the output token ceiling and
  stream if the response is long. ~1 hr
  **Done when:** a page with 10 violations gets all 10 explained, and
  `DECISIONS.md` records how many API calls one scan now costs.

- [ ] **5.8 Cache finished explanations** — the same rule violation yields the
  same explanation, so store it keyed by rule id and don't pay twice. On a zero
  budget this is load-bearing, not an optimisation. In-process dictionary is
  fine; note that it empties on restart. ~1 hr
  **Done when:** scanning the same URL twice makes no second API call, proven
  by a log line or counter.

- [ ] **5.9 Add prompt caching** — your system prompt is identical on every
  request, so mark it cached and it bills at a fraction of the rate. Order
  matters: stable content first, the per-scan violations last. ~1 hr
  **Done when:** `usage.cache_read_input_tokens` is above zero on the second
  scan. If it's zero, something in your prefix is changing between requests.

- [ ] **5.10 Tests with the API mocked out** — tests must never call the real
  API: slow, flaky, and they'd spend money on every run and every CI build.
  Replace the client with a stub returning a canned response. ~1 hr
  **Done when:** `pytest` passes with no network and no API key set.

- [ ] **5.11 Measure the cost per scan** — count tokens with the API's own
  `count_tokens` (never a third-party tokenizer — it gives wrong numbers for
  Claude), work out one average scan, write it in `DECISIONS.md`. ~45 min
  **Done when:** `DECISIONS.md` states the measured cost of one scan and what
  100 scans would cost.

---

## Phase 6 — The gate and the ceiling

**Both must be finished before the app is ever reachable from the internet.**

- [ ] **6.1 Hard daily spend ceiling** — a server-side counter of API calls (or
  tokens) per day. Past the limit, scanning returns axe results with
  explanations unavailable — the 5.6 path — instead of spending money. This is
  the one thing standing between a forwarded link and an empty account. ~1 hr
  **Done when:** with the cap set to 1, the second scan of the day returns a
  clear "daily limit reached" result and makes no API call.

- [ ] **6.2 Access code for live scanning** — one shared secret, from `.env`,
  checked by the backend on `/scan`. Prefer a code entered once and remembered
  in the browser over a secret pasted in the URL, since URLs leak through
  browser history and referrer headers. ~1 hr
  **Done when:** `POST /scan` without the code is refused, with it succeeds,
  and the code appears nowhere in the repo.

- [ ] **6.3 Simple rate limiting** — a modest per-IP limit. With a shared link
  rather than open access this is a second line of defence, so keep it small
  and simple. ~45 min
  **Done when:** rapid repeat requests get a 429 with a clear message.

---

## Phase 7 — Frontend skeleton

- [ ] **7.1 Scaffold Vite + React + TypeScript** — in `frontend/`, on
  `localhost:5173`. ~30 min
  **Done when:** `npm run dev` serves the starter page and `npm run build`
  finishes with no TypeScript errors.

- [ ] **7.2 Install and configure Tailwind** — plus a small palette chosen for
  contrast *now* rather than retrofitted in Phase 9. Four colours is plenty.
  ~45 min
  **Done when:** a Tailwind class visibly styles something, and your palette's
  text-on-background pairs are recorded with their measured contrast ratios.

- [ ] **7.3 Set up Vitest and React Testing Library** — plus one trivial test,
  for the same reason as 2.2. ~45 min
  **Done when:** `npm test` runs and reports 1 passed.

- [ ] **7.4 Typed API client** — TypeScript types written by hand from
  `docs/api-contract.md`, one `scanUrl()` function, base URL and access code
  from config so local and production differ only by configuration. ~1 hr
  **Done when:** `scanUrl()` against your local backend returns typed data and
  `npm run build` type-checks clean.

---

## Phase 8 — Frontend UI

- [ ] **8.1 The public demo page** — a real saved report from a real scan,
  stored as a JSON file in the frontend and rendered instantly with **no
  backend call**. Build it first: it's the one thing every portfolio reviewer
  will see, it works while the free-tier backend is asleep, and it gives every
  later task something to render. ~1 hr
  **Done when:** the demo page renders a full report with the backend
  completely switched off.

- [ ] **8.2 The URL input form** — labelled input, submit button, client-side
  validation, disabled while submitting. ~1 hr
  **Done when:** submitting a URL calls the backend and the result appears;
  submitting empty shows an inline message without calling it.

- [ ] **8.3 The access code screen** — asked for once, remembered in the
  browser, with a clear message when it's wrong. ~45 min
  **Done when:** a correct code unlocks scanning and survives a page reload; a
  wrong one explains itself.

- [ ] **8.4 The loading state** — a scan takes several seconds and a cold
  backend takes longer, so silence reads as breakage. Show continuous progress
  and say what's happening. ~45 min
  **Done when:** a real scan shows unbroken feedback from submit to result.

- [ ] **8.5 The results list** — grouped by severity, worst first, count per
  group. ~1 hr
  **Done when:** scanning a messy real site renders a readable grouped list.

- [ ] **8.6 The single-issue view** — selector, offending HTML, Claude's
  explanation, the corrected snippet in a code block with a copy button, and a
  link to the WCAG or MDN reference. ~1 hr
  **Done when:** you can read one issue end to end and copy its fix.

- [ ] **8.7 Show the guesses as guesses** — render the assumptions from 5.4
  visibly against the snippet, so nobody pastes an invented `alt` text
  believing the tool knew what the image showed. Decide the wording; "Claude
  assumed…" is clearer than a warning triangle. ~1 hr
  **Done when:** a missing-`alt` fix displays its assumption in a way a
  stranger reads before copying, confirmed by showing it to one person.

- [ ] **8.8 Every error state** — invalid URL, blocked URL, page unreachable,
  scan timed out, backend asleep, wrong access code, daily limit reached. Seven
  cases, each with a plain message saying what to do next. ~1 hr
  **Done when:** you can trigger all seven and none shows a raw status code or
  an empty screen.

- [ ] **8.9 The clean-page state** — what a page with no violations looks like,
  including the honest caveat that automated tools catch roughly a third of
  real accessibility problems. ~45 min
  **Done when:** scanning a well-built page shows a clear "nothing found"
  message carrying that caveat.

---

## Phase 9 — A11y-Lens must pass its own test (WCAG AA)

`CLAUDE.md` requires this, it's the one bug an accessibility tool cannot ship
with, and for a portfolio piece it's the centrepiece — a reviewer will tab
through your app specifically to check.

- [ ] **9.1 Full keyboard operation** — tab order follows reading order, focus
  always visibly outlined, Enter and Space behave, nothing mouse-only. ~1 hr
  **Done when:** you complete a whole scan and read a result without touching
  the mouse.

- [ ] **9.2 Semantics and landmarks** — real `<main>`, `<nav>`, `<h1>`, proper
  `<label>` associations, no skipped heading levels, and `<button>` rather than
  clickable `<div>`s. ~1 hr
  **Done when:** your own axe scan of `localhost:5173` returns zero violations.

- [ ] **9.3 Announce results to screen readers** — results appear without a
  page reload, so a screen reader user gets no notification unless you add a
  live region. ~45 min
  **Done when:** the results container announces itself when it fills, tested
  in a real screen reader (NVDA on Windows is free).

- [ ] **9.4 Contrast audit** — every text-on-background pair in the finished UI
  against 4.5:1 for body text, 3:1 for large. Disabled controls, placeholder
  text and your severity colours are the usual failures. ~45 min
  **Done when:** every pair is recorded with its ratio and none is below
  threshold.

- [ ] **9.5 Automated accessibility test in the suite** — run axe against your
  own built frontend as part of `npm test`, so a regression fails the build
  instead of waiting to be noticed. ~1 hr
  **Done when:** `npm test` includes an axe check that fails when you
  deliberately remove a label.

- [ ] **9.6 Reduced motion and zoom** — honour `prefers-reduced-motion`, stay
  usable at 200% zoom and 320px width. ~45 min
  **Done when:** fully usable at 200% zoom with no horizontal page scrolling.

---

## Phase 10 — Deploy

- [ ] **10.0 Choose the backend host** — Phase 1.2 measured a scan peaking near
  859MB, so a 512MB free tier is out. Compare what is actually available at the
  time (free tiers change constantly — the notes in `DECISIONS.md` are from
  2 Nov 2026 and must be re-verified) on memory ceiling, whether a card is
  required, and idle spin-down behaviour. ~45 min
  **Done when:** `DECISIONS.md` names the host, its memory ceiling, and what it
  costs if the free allowance runs out.

- [ ] **10.1 Make the backend deployable** — Playwright needs system browser
  libraries absent from a plain Python image; this is the most common deploy
  failure here. Pin the Python version and install the browser in the build.
  Then settle the question Phase 1.2 could not: run the container with a hard
  memory cap (`docker run -m <limit>`) and confirm a scan survives it, since a
  Windows measurement is indicative only. ~1 hr
  **Done when:** a local container build with a hard memory cap runs a
  successful scan without being killed.

- [ ] **10.2 Deploy the backend** — service created on the host chosen in 10.0,
  environment variables set in its dashboard (never committed), `/health`
  reachable publicly. ~1 hr
  **Done when:** the public `/health` returns ok and a real `POST /scan` with
  the access code returns violations.

- [ ] **10.3 Deploy the frontend to Vercel** — pointing at the backend URL via a
  build-time env var. ~45 min
  **Done when:** the public Vercel URL shows the demo page instantly, and a
  real scan works once the code is entered.

- [ ] **10.4 Lock CORS to your Vercel domain** — the permissive local setting
  from 2.4 must not survive into production. ~30 min
  **Done when:** your Vercel site works and a `fetch` from any other origin is
  refused.

- [ ] **10.5 Handle the cold start** — free tiers sleep; the first scan after
  idle can take 30+ seconds or fail. The demo page already covers the first
  impression, so this is about the scan itself: make the frontend's timeout
  match the backend's and say something honest while waiting. ~45 min
  **Done when:** a scan after an hour of inactivity either succeeds or shows a
  "waking up, try again" message — never a silent failure.

- [ ] **10.6 Verify the ceiling in production** — confirm the daily cap and
  access code actually work on the deployed app, not just locally. Config
  differs between environments, and this is the one failure that costs money.
  ~45 min
  **Done when:** the deployed app refuses a scan without the code, and
  `DECISIONS.md` records the production cap.

---

## Phase 11 — CI and documentation

- [ ] **11.1 Run both test suites on every PR** — a GitHub Actions workflow
  running `pytest` and `npm test`. ~1 hr
  **Done when:** a PR shows both suites passing as checks, and a deliberately
  broken test blocks the PR.

- [ ] **11.2 Finish the README** — what it does, a screenshot, the demo link,
  local setup for both halves, environment variables, how to deploy, and the
  honest limits of automated accessibility testing. For a portfolio piece this
  is the most-read file in the repo. ~1 hr
  **Done when:** you follow your own README from a fresh clone and reach a
  working local app without consulting anything else.

- [ ] **11.3 Tidy DECISIONS.md** — read it end to end, fix what's no longer
  true, add anything you decided but never wrote down. ~30 min
  **Done when:** every entry is accurate about the code as it now stands.
