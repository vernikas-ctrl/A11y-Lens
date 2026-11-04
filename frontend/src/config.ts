/**
 * Where the backend is, and the code needed to talk to it.
 *
 * Both come from the environment, never from a literal in a component, so
 * that local development and the deployed app differ only by configuration.
 * Task 10.4 points this at the real backend by setting one variable in
 * Vercel; no code changes.
 *
 * Vite only exposes variables whose names begin with `VITE_`, and it
 * substitutes them at build time. Two things follow from that, and the second
 * one matters:
 *
 * 1. A variable added to `.env` after `npm run dev` started will not appear
 *    until the dev server is restarted.
 * 2. **Anything here ends up inside the built JavaScript, which anybody who
 *    can load the page can read.** The access code is not a secret in the way
 *    the backend's ANTHROPIC_API_KEY is a secret. It keeps the link from
 *    being casually usable by a stranger who finds it; it does not protect
 *    anything from somebody who opens developer tools. That is the honest
 *    limit of a shared code in a frontend, and it is written here rather than
 *    somewhere nobody will look.
 *
 * The real values live in `frontend/.env`, which is git-ignored.
 * `.env.example` carries the shape with placeholder values.
 */

/** Trailing slashes removed, so `${API_BASE_URL}/scan` never doubles up. */
function readBaseUrl(): string {
  const raw = import.meta.env.VITE_API_BASE_URL
  if (typeof raw !== 'string' || raw.trim() === '') {
    // Defaulting to the local backend rather than throwing: a fresh clone
    // with no .env should run, and the port is the one the backend's README
    // tells you to use. A wrong *remote* URL is a deployment mistake and
    // shows up immediately as a failed request.
    return 'http://127.0.0.1:8000'
  }
  return raw.trim().replace(/\/+$/, '')
}

export const API_BASE_URL = readBaseUrl()

/**
 * The shared access code, or an empty string when none is configured.
 *
 * Empty is a legitimate state rather than an error: task 8.0 shows the code
 * screen, the person types a code, and the app holds it from then on. This
 * value is only the build-time default, which is convenient in development
 * and normally unset in production.
 */
export const ACCESS_CODE: string = (import.meta.env.VITE_ACCESS_CODE ?? '').trim()

/*
 * ---------------------------------------------------------------------------
 * How long to wait before giving up on a request. Task 10.5.
 * ---------------------------------------------------------------------------
 *
 * This was a flat 90 seconds, with a comment saying the backend's own ceiling
 * was 30. Both halves of that were wrong, and the consequence was a real bug.
 *
 * The backend spends `SCAN_TIMEOUT_MS` *twice*, in series: once navigating to
 * the page (`scanner.py`, `_goto`) and again as a separate budget for the axe
 * run (`scanner.py`, `scan`). Then `EXPLAIN_TIMEOUT_MS` on top of both. So its
 * worst legitimate case is 30 + 30 + 60 = 120 seconds before a millisecond is
 * spent launching Chromium or crossing the network.
 *
 * Giving up at 90 therefore guaranteed one specific failure: a slow page that
 * was going to succeed would be reported to the person as a timeout while the
 * backend still had thirty seconds of budget left and a finished report on the
 * way. The old comment said "too short a timeout here would report a failure
 * for a scan that was about to succeed" -- and then set one.
 *
 * So the number is derived here rather than chosen, and `config.test.ts`
 * fails the build if the backend's ceilings move without this moving with
 * them.
 */

/** `SCAN_TIMEOUT_MS`, as `backend/.env.example` and `config.py` both set it. */
const BACKEND_SCAN_TIMEOUT_MS = 30_000

/** `EXPLAIN_TIMEOUT_MS`, likewise. */
const BACKEND_EXPLAIN_TIMEOUT_MS = 60_000

/**
 * How many times a scan spends the page-load budget, one after another: the
 * navigation, then the axe run.
 *
 * This is the number that made the old timeout wrong, so it is a constant with
 * a test behind it rather than arithmetic in a comment. `config.test.ts`
 * checks both places in `scanner.py` are still there, which means adding a
 * third breaks the build instead of the deployed app.
 */
const SCAN_BUDGETS_SPENT = 2

/** The longest the backend can legitimately take, by its own configuration. */
export const BACKEND_WORST_CASE_MS =
  SCAN_BUDGETS_SPENT * BACKEND_SCAN_TIMEOUT_MS + BACKEND_EXPLAIN_TIMEOUT_MS

/**
 * What to allow on top, for everything the backend's own ceilings do not
 * cover: Cloud Run starting a container that has Chromium inside it, Python
 * importing, uvicorn binding, Playwright launching a browser, and the request
 * crossing the network twice.
 *
 * **This is an estimate, and it is the one number here that is not derived
 * from something.** Task 10.5's production check replaces it with a measured
 * value once there is a deployed backend to measure. It is deliberately
 * generous: being too patient costs a person some seconds in front of a
 * progress panel that tells them what is happening, while being too impatient
 * costs them a report that had already been written.
 */
const COLD_START_ALLOWANCE_MS = 45_000

/**
 * Overridable, because the backend's ceilings are environment variables on the
 * host and can be changed there without a frontend deploy.
 *
 * A value below the backend's own worst case is refused in favour of that
 * worst case, and says so in the console. Such a value cannot prevent a real
 * failure -- the backend gives up on its own by then -- it can only invent
 * one. If the intention really is a shorter wait, the place to shorten it is
 * `SCAN_TIMEOUT_MS` and `EXPLAIN_TIMEOUT_MS` on the backend, and then this.
 */
function readTimeout(): number {
  const fallback = BACKEND_WORST_CASE_MS + COLD_START_ALLOWANCE_MS
  const raw = import.meta.env.VITE_REQUEST_TIMEOUT_MS
  if (typeof raw !== 'string' || raw.trim() === '') return fallback

  const parsed = Number(raw.trim())
  if (!Number.isFinite(parsed) || parsed <= 0) {
    console.warn(
      `VITE_REQUEST_TIMEOUT_MS is not a number of milliseconds ` +
        `(${raw}); using ${fallback}ms instead.`,
    )
    return fallback
  }

  if (parsed < BACKEND_WORST_CASE_MS) {
    console.warn(
      `VITE_REQUEST_TIMEOUT_MS is ${parsed}ms, which is below the ` +
        `${BACKEND_WORST_CASE_MS}ms the backend may legitimately take. A ` +
        `budget that short can only report scans that were about to succeed ` +
        `as failures, so ${BACKEND_WORST_CASE_MS}ms is being used instead.`,
    )
    return BACKEND_WORST_CASE_MS
  }

  return parsed
}

export const REQUEST_TIMEOUT_MS = readTimeout()
