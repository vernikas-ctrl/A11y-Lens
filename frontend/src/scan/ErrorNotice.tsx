/**
 * Every way a scan can fail, said in plain words. Task 8.8.
 *
 * The task asks for seven cases. There are ten of the contract's codes plus
 * three the backend never sees, so this covers thirteen -- the extra ones are
 * cheap once the shape exists, and a code with no case would fall through to
 * a bare status number, which is the thing being avoided.
 *
 * **The backend's `message` is shown as-is.** Contract rule 1: the frontend
 * branches on `code` and never on `message`. Rewording here would mean two
 * places decide what somebody reads, and they would drift.
 *
 * What this adds is the next line: what to *do*. The backend knows what went
 * wrong; only the frontend knows what is on screen and what the person could
 * try next. "That page could not be reached" is a diagnosis; "check the
 * address opens in a normal browser tab" is an instruction.
 */

import type { ClientErrorCode, ApiFailure } from '../api/client'

/**
 * What to try next, per code.
 *
 * **Strictly additive.** The backend's own message is printed directly above
 * this, so anything that repeats it reads as a stutter. The first live check
 * showed exactly that: the backend says "This is deliberate, not a fault."
 * and this line said it again, two lines later. Each entry below is written
 * against the real text in `backend/app/errors.py`, and a test asserts no
 * sentence appears twice in a rendered failure.
 *
 * They must also be true in every state this notice can appear in. The first
 * draft of the daily-limit line pointed at "the example report further down",
 * which is only there until a real scan replaces it -- so by the time anybody
 * hit the cap, the advice was describing something no longer on screen.
 */
const WHAT_TO_DO: Record<ClientErrorCode, string> = {
  invalid_url:
    'It should look like https://example.com — check for a missing letter or an extra space.',
  blocked_address:
    'Only pages on the open web can be scanned, so localhost, 127.0.0.1 and anything on a home or office network are refused.',
  unauthorized:
    'The code is no longer being accepted. It may have been changed since you were given it.',
  not_found:
    'Nothing you did caused this, and nothing you try will fix it. Worth reporting.',
  method_not_allowed:
    'Nothing you did caused this, and nothing you try will fix it. Worth reporting.',
  rate_limited:
    'Scans are capped at a few per minute so the service stays affordable to run.',
  daily_limit_reached:
    'The cap covers the whole service rather than each person, and it is what keeps this free to run.',
  unreachable:
    'Pages behind a login, and pages only reachable inside a company network, cannot be scanned from here.',
  scan_timeout:
    'Very heavy pages sometimes never finish. A simpler page on the same site is usually a better test.',
  internal_error:
    'If it happens again on the same address, that is worth reporting.',
  network_error:
    'If this is the first scan in a while the server may be waking up, which takes about half a minute. Otherwise check your connection.',
  request_timeout:
    'Either the page is unusually slow or the server is still waking up. A moment and another go usually settles it.',
  malformed_response:
    'Something between you and A11y-Lens answered instead of A11y-Lens. Worth reporting.',
}

/** Codes where trying the same thing again might genuinely work. */
const WORTH_RETRYING: ReadonlySet<ClientErrorCode> = new Set<ClientErrorCode>([
  'unreachable',
  'scan_timeout',
  'internal_error',
  'network_error',
  'request_timeout',
])

/**
 * Task 10.5. The one failure a cold host is most likely to produce, and the
 * one case above that was getting the wrong treatment.
 *
 * `client.ts` turns a response it cannot parse into `malformed_response`, and
 * its own comment says why: "a proxy or a sleeping host can answer with an
 * HTML error page". A free host waking up does exactly that -- Cloud Run
 * answers a request that arrives before the container is serving with its own
 * 5xx page, which is HTML and not the contract's shape.
 *
 * So the single most likely cold-start failure was landing on the one code
 * that offers no "try again" button and says "Worth reporting." Retrying is
 * precisely what fixes it, and reporting it achieves nothing.
 *
 * Split by status rather than by code: a 5xx is the host, while a 2xx or 4xx
 * that is not the contract's shape really is a bug in this app.
 */
function hostIsStillStarting(failure: ApiFailure): boolean {
  return (
    failure.code === 'malformed_response' &&
    failure.status !== null &&
    failure.status >= 500
  )
}

/** The cold-start wording, which replaces the bug-report wording above. */
const HOST_STARTING_ADVICE =
  'Nothing is broken and nothing needs reporting. The server sleeps when nobody is using it, and the first request wakes it; give it half a minute and try again.'

interface Props {
  failure: ApiFailure
  /** Offered only where retrying could help; absent otherwise. */
  onRetry?: () => void
}

export default function ErrorNotice({ failure, onRetry }: Props) {
  const starting = hostIsStillStarting(failure)
  const advice = starting ? HOST_STARTING_ADVICE : WHAT_TO_DO[failure.code]
  const canRetry =
    onRetry !== undefined && (starting || WORTH_RETRYING.has(failure.code))

  return (
    // role="alert" because this replaces what the person was waiting for.
    // A screen reader user who submitted a scan and heard nothing would be
    // left watching a page that never said anything.
    <div
      role="alert"
      className="rounded-md border border-alert bg-surface p-4"
    >
      <h2 className="font-medium text-alert">Scan failed</h2>

      {/* The backend's own words, unedited. */}
      <p className="mt-1 text-ink">{failure.message}</p>

      {advice && <p className="mt-2 text-sm text-ink">{advice}</p>}

      {failure.retryAfterSeconds !== undefined && (
        <p className="mt-2 text-sm text-ink">
          Try again in {failure.retryAfterSeconds} seconds.
        </p>
      )}

      {canRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-md bg-primary px-4 py-2 text-sm font-medium text-paper"
        >
          Try the scan again
        </button>
      )}

      {/* Small, last, and only when there is something in it. Useful when
          somebody reports a fault; ignorable otherwise. A raw status code on
          its own is what task 8.8 forbids -- this is a status code with an
          explanation already above it. */}
      {failure.detail && (
        <p className="mt-3 text-xs text-muted">
          Detail: {failure.detail}
          {failure.status !== null && ` (HTTP ${failure.status})`}
        </p>
      )}
    </div>
  )
}
