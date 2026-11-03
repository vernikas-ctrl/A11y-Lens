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

/**
 * How long to wait before giving up on a request.
 *
 * Generous, because a scan runs a real browser against a real page: the
 * backend's own ceiling is 30 seconds and a cold free-tier host can take
 * longer than that to wake up before it even starts. Too short a timeout here
 * would report a failure for a scan that was about to succeed.
 */
export const REQUEST_TIMEOUT_MS = 90_000
