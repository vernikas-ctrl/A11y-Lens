/**
 * The only module that knows how to talk to the backend.
 *
 * Deliberately mirrors `backend/app/explainer.py`: one module owns one
 * boundary, so a component never builds a request by hand and nothing else
 * needs to know what a header is.
 *
 * **Nothing here throws for an expected failure.** Every call returns a
 * `ApiResult`, which is either `{ ok: true, data }` or `{ ok: false, error }`.
 * TypeScript then refuses to let a caller read `data` without checking `ok`
 * first, which is a compile-time version of the thing the backend achieves by
 * never letting the explanation step fail a scan. The alternative -- throwing
 * -- makes the failure path invisible in the types, and the failure path here
 * includes every one of the contract's ten error codes plus the network
 * itself.
 */

import { ACCESS_CODE, API_BASE_URL, REQUEST_TIMEOUT_MS } from '../config'
import type { ApiErrorBody, ErrorCode, Health, Report } from './types'

/**
 * The contract's codes, plus three that describe failures which never reach
 * the backend at all.
 *
 * These three are not in `docs/api-contract.md` on purpose: the contract
 * describes what the backend says, and the backend cannot say anything when
 * the request never arrives. They are named distinctly so a caller can tell
 * "the server refused this" from "the server was not there", which are
 * different messages to show a person.
 */
export type ClientErrorCode =
  | ErrorCode
  | 'network_error'
  | 'request_timeout'
  | 'malformed_response'

export interface ApiFailure {
  code: ClientErrorCode
  /** Safe to show as-is. From the backend when it answered, ours when it did not. */
  message: string
  detail: string | null
  /** The HTTP status, or null when there was no response. */
  status: number | null
  /** From the `Retry-After` header on a 429, when the backend sent one. */
  retryAfterSeconds?: number
}

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiFailure }

/** What we say when the backend did not get a chance to say anything. */
const TRANSPORT_MESSAGES: Record<
  'network_error' | 'request_timeout' | 'malformed_response' | 'host_not_ready',
  string
> = {
  network_error:
    'Could not reach A11y-Lens. Check your connection, or the backend may be starting up.',
  request_timeout:
    'A11y-Lens took too long to answer. The page may be very slow, or the backend may be waking up.',
  malformed_response:
    'A11y-Lens sent back something unexpected. This is a bug, not something you did wrong.',
  host_not_ready:
    'A11y-Lens is not answering yet: something in front of it replied instead. That is what a server still starting up looks like.',
}

/**
 * Task 10.5. Both messages above belong to the same `malformed_response`
 * code, and the status says which of them is true.
 *
 * The code stays one code on purpose -- contract rule 1 is that callers branch
 * on `code`, and a new code would mean a new case in every exhaustive switch
 * over it. What changes is only the sentence, because the two situations are
 * not alike: a 2xx or 4xx that is not the contract's shape is a bug in this
 * app and somebody should hear about it, while a 5xx HTML page from a free
 * host that is still launching Chromium is a wait, and the thing to do about
 * it is wait.
 */
function malformedMessage(status: number): string {
  return status >= 500 ? TRANSPORT_MESSAGES.host_not_ready : TRANSPORT_MESSAGES.malformed_response
}

export interface RequestOptions {
  /**
   * Overrides the build-time code from config. Task 8.0 passes the code the
   * person typed, which is why this is a parameter rather than read from
   * configuration inside each function.
   */
  accessCode?: string
  /** For cancelling a request when a component unmounts or a user navigates away. */
  signal?: AbortSignal
}

function failure(
  code: ClientErrorCode,
  message: string,
  detail: string | null,
  status: number | null,
  retryAfterSeconds?: number,
): { ok: false; error: ApiFailure } {
  const error: ApiFailure = { code, message, detail, status }
  if (retryAfterSeconds !== undefined) error.retryAfterSeconds = retryAfterSeconds
  return { ok: false, error }
}

/** Narrows an unknown parsed body to the contract's error shape. */
function isApiErrorBody(body: unknown): body is ApiErrorBody {
  if (typeof body !== 'object' || body === null) return false
  const wrapper = body as { error?: unknown }
  if (typeof wrapper.error !== 'object' || wrapper.error === null) return false
  const inner = wrapper.error as { code?: unknown; message?: unknown }
  return typeof inner.code === 'string' && typeof inner.message === 'string'
}

function retryAfterFrom(response: Response): number | undefined {
  const header = response.headers.get('Retry-After')
  if (header === null) return undefined
  const seconds = Number.parseInt(header, 10)
  // A `Retry-After` may legitimately be an HTTP date rather than a number of
  // seconds. We only send the number form, so anything else is ignored
  // rather than guessed at.
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : undefined
}

/**
 * One request, with the timeout, the header and every failure mode handled in
 * one place so the three public functions below stay readable.
 */
async function request<T>(
  path: string,
  init: RequestInit,
  options: RequestOptions,
): Promise<ApiResult<T>> {
  const code = options.accessCode ?? ACCESS_CODE

  // Our own timeout, combined with any signal the caller passed. `fetch` has
  // no timeout of its own: without this a request against a backend that
  // accepts the connection and then goes quiet would hang until the browser
  // gave up, which can be minutes.
  const timeout = new AbortController()
  const timer = setTimeout(() => timeout.abort(), REQUEST_TIMEOUT_MS)
  const signals = [timeout.signal]
  if (options.signal) signals.push(options.signal)

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        ...init.headers,
        // Sent even when empty, so the backend answers `unauthorized` -- which
        // is a message the UI can show -- rather than the different error it
        // would produce for a missing header.
        'X-Access-Code': code,
      },
      signal: AbortSignal.any(signals),
    })
  } catch (caught) {
    clearTimeout(timer)
    // A caller cancelling on purpose is not a failure to report, so it is
    // re-thrown and the caller's own cleanup deals with it.
    if (options.signal?.aborted) throw caught
    if (timeout.signal.aborted) {
      return failure('request_timeout', TRANSPORT_MESSAGES.request_timeout, null, null)
    }
    // `fetch` rejects for DNS failures, refused connections, TLS problems and
    // CORS refusals alike, and deliberately does not say which -- the browser
    // treats the distinction as information a page should not have.
    const detail = caught instanceof Error ? caught.message : null
    return failure('network_error', TRANSPORT_MESSAGES.network_error, detail, null)
  } finally {
    clearTimeout(timer)
  }

  let body: unknown
  try {
    body = await response.json()
  } catch {
    // A proxy or a sleeping host can answer with an HTML error page, which is
    // not the contract's shape and cannot be parsed. Treated as malformed
    // rather than crashing on `.json()`.
    return failure(
      'malformed_response',
      malformedMessage(response.status),
      `The response to ${path} was not JSON.`,
      response.status,
    )
  }

  if (!response.ok) {
    if (isApiErrorBody(body)) {
      return failure(
        body.error.code,
        body.error.message,
        body.error.detail ?? null,
        response.status,
        retryAfterFrom(response),
      )
    }
    // JSON, but not the contract's shape. Rule 7 says the backend never
    // returns a bare string or array, so this means something in front of the
    // backend answered instead of the backend.
    return failure(
      'malformed_response',
      malformedMessage(response.status),
      `${path} returned ${response.status} without an error code.`,
      response.status,
    )
  }

  return { ok: true, data: body as T }
}

/**
 * Contract 1. Used to tell "the backend is asleep" from "the scan failed",
 * which are different things to tell a person.
 */
export function checkHealth(options: RequestOptions = {}): Promise<ApiResult<Health>> {
  return request<Health>('/health', { method: 'GET' }, options)
}

/**
 * Is this access code right? Nothing else.
 *
 * Task 8.0's code screen calls this. Returns `ok: true` for a valid code and
 * an `unauthorized` failure for an invalid one -- both are successful
 * *answers*, so a caller that wants a plain yes/no can check
 * `result.ok || result.error.code !== 'unauthorized'` to tell a wrong code
 * from a backend that could not be reached.
 */
export function verifyCode(
  accessCode: string,
  options: RequestOptions = {},
): Promise<ApiResult<{ ok: boolean }>> {
  return request<{ ok: boolean }>('/verify', { method: 'POST' }, { ...options, accessCode })
}

/**
 * Contract 2. Scan one page.
 *
 * A successful result may still be a degraded one: check
 * `data.explanations_available` before reading any `explanation` or `fix`,
 * which are null together when it is false.
 */
export function scanUrl(url: string, options: RequestOptions = {}): Promise<ApiResult<Report>> {
  return request<Report>(
    '/scan',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    },
    options,
  )
}
