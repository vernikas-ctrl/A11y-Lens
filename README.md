# A11y-Lens

A web app that finds accessibility problems on a web page and explains them in
plain language. You give it a URL; it opens that page in a real browser, scans
it with [axe-core](https://github.com/dequelabs/axe-core), and uses the Claude
API to turn each raw finding into something you can act on — what is wrong, who
it affects, and a corrected code snippet. Anything Claude had to guess is
marked as a guess, so you never paste in an invented `alt` text believing the
tool knew what the image showed.

<!-- SCREENSHOT -->

**Status:** in development, and deliberately not deployed yet. The live link
goes here once task 10.3 is done; see [TASKS.md](TASKS.md) for what is left.

---

## What it actually does

1. You enter a URL and the shared access code.
2. The backend checks the address is a real public web page — **loopback and
   private network ranges are refused**, because a scanner that will fetch
   anything is a tool for reading things it should not.
3. Playwright opens the page in a headless Chromium and runs axe-core against
   it.
4. Each finding goes to the Claude API, which writes the explanation and the
   corrected snippet.
5. You get one report: what is broken, how badly, and what to paste instead.

**A scan still works with no Claude API key.** You get the findings without
the explanations, clearly marked as unavailable rather than silently empty.
That is also the honest fallback when the API is down or the daily cap is
reached, and it means you can run this project end to end without spending
anything.

## The limits, up front

**Automated tools catch roughly a third of real accessibility problems.** A
clean report from A11y-Lens means no *detectable* issues — not an accessible
page. Nothing automated can tell you whether your alt text is *accurate*,
whether your headings describe the content, or whether the page makes sense
read aloud in order. Those need a person, and ideally a person who uses a
screen reader.

What this tool is good at is the third it does catch, and at explaining that
third well enough that you can fix it today.

---

## Running it locally

You need **Python 3.14**, **Node 24**, and **git**. The app is two programs,
so you will end up with two terminals.

### 1. The backend

```bash
cd backend
python -m venv .venv
```

Then, on **Windows**:

```bash
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m playwright install chromium
```

or on **macOS and Linux**:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
```

`playwright install chromium` downloads a browser, which is ~150MB and the
slow part of setup. Skipping it is the most common first-run failure: every
other step appears to work, and then the first scan fails.

Now the configuration:

```bash
cp .env.example .env
```

Open `backend/.env` and set **`ACCESS_CODE`** to anything at least 12
characters long. You can leave `ANTHROPIC_API_KEY` as the placeholder — the
app starts without a real key and returns findings without explanations.

Start it:

```bash
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

`http://127.0.0.1:8000/health` should answer `{"status": "ok", ...}`.

### 2. The frontend

In a second terminal:

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open `frontend/.env` and set **`VITE_ACCESS_CODE` to the same value you put in
`backend/.env`**. If the two differ, every scan comes back `unauthorized`, and
that is the single most likely reason a fresh setup does not work.

Then open **http://localhost:5173**.

> Vite reads `.env` when it starts. A value changed while `npm run dev` is
> already running does nothing until you restart it.

### If something is wrong

| What you see | What it usually is |
|---|---|
| `unauthorized` on every scan | The two access codes do not match |
| The backend refuses to start | `.env` is missing, or `ACCESS_CODE` is under 12 characters. It says which |
| The first scan fails, everything else works | `playwright install chromium` was skipped |
| Explanations say "unavailable" | No real `ANTHROPIC_API_KEY`. Expected, and the findings are still real |
| `localhost` is refused as a URL to scan | Deliberate. Loopback and private addresses are blocked |

---

## Environment variables

Both halves read a git-ignored `.env`, and both have a committed
`.env.example` listing every key with placeholder values. **Only two have no
default.**

### `backend/.env`

| Variable | Default | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | *required* | Claude API key. The placeholder value is accepted in development |
| `ACCESS_CODE` | *required* | Shared code that unlocks scanning. At least 12 characters |
| `ALLOWED_ORIGINS` | `http://localhost:5173` | Origins the browser may call the API from (CORS) |
| `SCAN_TIMEOUT_MS` | `30000` | How long a page may take to load. Spent **twice**: the navigation, then the axe run |
| `EXPLAIN_TIMEOUT_MS` | `60000` | How long the explanation call may take before the scan returns findings without it |
| `DAILY_SCAN_LIMIT` | `15` | Scans per day for the whole service. This is what bounds the bill |
| `RATE_LIMIT_PER_MINUTE` | `5` | Requests per address per minute |
| `ANTHROPIC_MODEL` | `claude-opus-5-5` | Configuration rather than a constant, because the choice is a cost decision |
| `ANTHROPIC_EFFORT` | `low` | How much the model thinks before answering. Billed as output, so the main cost dial |
| `ENVIRONMENT` | `development` | `production` refuses to start on a placeholder API key |
| `TRUSTED_PROXY_HOPS` | `0` | How many proxies sit in front, for reading the client address safely |

### `frontend/.env`

| Variable | Default | What it does |
|---|---|---|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | Where the backend is |
| `VITE_ACCESS_CODE` | *(empty)* | Build-time default for the code. Normally **unset in production** |
| `VITE_REQUEST_TIMEOUT_MS` | *derived* | How long to wait for a scan. Worked out from the backend's ceilings plus a cold-start allowance |

> **`VITE_ACCESS_CODE` is not a secret the way the API key is a secret.** Vite
> compiles it into the JavaScript the browser downloads, so anybody who opens
> developer tools can read it. It keeps a forwarded link from being casually
> usable by a stranger; it is not protection against somebody who wants in.
> The backend's `ANTHROPIC_API_KEY` never comes near the browser.

---

## Tests

```bash
cd backend  && .venv/Scripts/python -m pytest     # 294 tests
cd frontend && npm test                           # 184 tests
```

Both run on every pull request — see
[`.github/workflows/tests.yml`](.github/workflows/tests.yml).

Neither suite needs the internet, with one exception. The frontend stubs
`fetch`; the backend launches a real Chromium but points it at
`tests/fixtures/broken.html` on disk, so it does not depend on anybody else's
uptime. The exception is **DNS**: the endpoint tests post `example.com` and
the address checker resolves it for real.

Other commands worth knowing:

| Command | Where | What it does |
|---|---|---|
| `npm run build` | `frontend` | Type-checks, then builds into `dist/` |
| `npm run lint` | `frontend` | oxlint |
| `npm run smoke` | `frontend` | Checks the API client against a **running** backend |
| `npm run contrast` | `frontend` | Prints the palette's measured contrast ratios |
| `python scripts/memory_check.py` | `backend` | Measures what a scan costs in memory |
| `python scripts/container_check.py` | `backend` | Builds the image and scans under a hard memory cap |

## Deploying

Decided in Phase 10 and written up in [DECISIONS.md](DECISIONS.md).

**The backend goes on Google Cloud Run** — 2 GiB and 1 vCPU, request-based
billing, scaling to zero when idle. 2 GiB because a scan peaks near 859MB,
which rules out every 512MB free tier. `backend/Dockerfile` builds the image,
and `backend/scripts/container_check.py` checks a scan survives a hard memory
cap before production finds out for you.

The daily cap is what makes this affordable. With `DAILY_SCAN_LIMIT` at 15,
the most the service can consume in a month is **7.8% of Cloud Run's free
allowance** — the Phase 6 ceiling bounds the hosting bill as well as the
Anthropic one.

**The frontend goes on Vercel**, pointed at the backend with
`VITE_API_BASE_URL`. Set the environment variables in each host's own
dashboard, never in a committed file.

## Layout

```
backend/
  app/            FastAPI app, scanner, explainer, URL safety, limits
  scripts/        Diagnostics: memory, cost, container, demo data
  tests/          The backend suite
frontend/
  src/            React app — see frontend/README.md
docs/
  api-contract.md The shape of every request and response
  scope.md        What is in v1 and what is not
  prompt.md       The prompt the explainer sends, and why it is shaped that way
CLAUDE.md         The rules this project is built under
DECISIONS.md      Why things are the way they are
TASKS.md          The plan, and what is done
```

## Licence

Not yet chosen.
