/**
 * The API client. Task 7.4.
 *
 * `fetch` is replaced with a stub, for the same reason the backend's tests
 * replace the Anthropic client: a test that needs a running backend is a test
 * nobody runs. The stub also makes failures testable that are hard to cause
 * on purpose -- a sleeping host answering with HTML, a 429 with a
 * `Retry-After`, a connection refused mid-request.
 *
 * The live check against a real backend is recorded in TASKS.md under 7.4;
 * these tests are about the shapes, not the connection.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { checkHealth, scanUrl, verifyCode } from './client'
import type { Report } from './types'

const BASE = 'http://127.0.0.1:8000'

/** A minimal valid report, per contract 2.1. */
function report(overrides: Partial<Report> = {}): Report {
  return {
    url: 'https://example.com/',
    page_title: 'Example Domain',
    scanned_at: '2026-11-03T10:30:00Z',
    scan_duration_ms: 4812,
    explanations_available: true,
    summary: { critical: 0, serious: 1, moderate: 0, minor: 0, total: 1 },
    issues: [
      {
        id: 'image-alt-0',
        rule_id: 'image-alt',
        severity: 'serious',
        wcag: ['1.1.1'],
        reference_url: 'https://dequeuniversity.com/rules/axe/4.10/image-alt',
        selector: 'main > img:nth-child(2)',
        html: '<img src="/logo.png">',
        explanation: { what: 'No alt attribute.', who: 'Screen reader users.' },
        fix: { language: 'html', snippet: '<img src="/logo.png" alt="Logo">', assumptions: [] },
      },
    ],
    ...overrides,
  }
}

/** Builds a `fetch` stub that answers once with the given body and status. */
function answers(body: unknown, init: { status?: number; headers?: Record<string, string> } = {}) {
  const status = init.status ?? 200
  return vi.fn(async () =>
    new Response(typeof body === 'string' ? body : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json', ...init.headers },
    }),
  )
}

function errorBody(code: string, message: string, detail: string | null = null) {
  return { error: { code, message, detail } }
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = answers(report())
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('scanUrl', () => {
  it('returns the report on success', async () => {
    const result = await scanUrl('https://example.com')

    expect(result.ok).toBe(true)
    // The `ok` check above is what lets TypeScript allow `result.data` here;
    // without it this line does not compile, which is the point of the shape.
    if (!result.ok) throw new Error('expected success')
    expect(result.data.summary.total).toBe(1)
    expect(result.data.issues[0].rule_id).toBe('image-alt')
  })

  it('sends the URL as JSON to the right address', async () => {
    await scanUrl('https://example.com')

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE}/scan`)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ url: 'https://example.com' })
  })

  it('sends the access code in a header, never in the URL', async () => {
    // Contract section 2: URLs leak through history, logs and Referer headers.
    await scanUrl('https://example.com', { accessCode: 'a-test-code-12345' })

    const [url, init] = fetchMock.mock.calls[0]
    expect(init.headers['X-Access-Code']).toBe('a-test-code-12345')
    expect(url).not.toContain('a-test-code-12345')
  })

  it('passes a degraded report through unchanged', async () => {
    // Contract 2.3: still a 200, and the findings are still worth having.
    vi.stubGlobal(
      'fetch',
      answers(
        report({
          explanations_available: false,
          explanations_unavailable_reason: 'api_unavailable',
          issues: [{ ...report().issues[0], explanation: null, fix: null }],
        }),
      ),
    )

    const result = await scanUrl('https://example.com')

    if (!result.ok) throw new Error('expected success')
    expect(result.data.explanations_available).toBe(false)
    expect(result.data.explanations_unavailable_reason).toBe('api_unavailable')
    expect(result.data.issues[0].explanation).toBeNull()
  })
})

describe('failures the backend reports', () => {
  it.each([
    ['invalid_url', 400],
    ['blocked_address', 400],
    ['unauthorized', 401],
    ['unreachable', 502],
    ['scan_timeout', 504],
    ['internal_error', 500],
  ])('surfaces %s as a typed failure, not an exception', async (code, status) => {
    vi.stubGlobal('fetch', answers(errorBody(code, 'Something went wrong.'), { status }))

    const result = await scanUrl('https://example.com')

    expect(result.ok).toBe(false)
    if (result.ok) throw new Error('expected failure')
    expect(result.error.code).toBe(code)
    expect(result.error.status).toBe(status)
    expect(result.error.message).toBe('Something went wrong.')
  })

  it('keeps the backend message rather than inventing one', async () => {
    // Contract rule 1: the frontend branches on `code` and shows `message`
    // as-is. Rewording it here would mean two places decide what the user
    // reads, and they would drift.
    const message = 'That address points inside a private network.'
    vi.stubGlobal('fetch', answers(errorBody('blocked_address', message, 'Resolved to 127.0.0.1'), { status: 400 }))

    const result = await scanUrl('http://localhost')

    if (result.ok) throw new Error('expected failure')
    expect(result.error.message).toBe(message)
    expect(result.error.detail).toBe('Resolved to 127.0.0.1')
  })

  it('reads Retry-After from a rate limit', async () => {
    vi.stubGlobal(
      'fetch',
      answers(errorBody('rate_limited', 'Too many scans.'), {
        status: 429,
        headers: { 'Retry-After': '42' },
      }),
    )

    const result = await scanUrl('https://example.com')

    if (result.ok) throw new Error('expected failure')
    expect(result.error.code).toBe('rate_limited')
    expect(result.error.retryAfterSeconds).toBe(42)
  })

  it('ignores a Retry-After it cannot read as seconds', async () => {
    // The header may legitimately be an HTTP date. We only send the numeric
    // form, so anything else is left out rather than guessed at.
    vi.stubGlobal(
      'fetch',
      answers(errorBody('rate_limited', 'Too many scans.'), {
        status: 429,
        headers: { 'Retry-After': 'Tue, 03 Nov 2026 12:00:00 GMT' },
      }),
    )

    const result = await scanUrl('https://example.com')

    if (result.ok) throw new Error('expected failure')
    expect(result.error.retryAfterSeconds).toBeUndefined()
  })

  it('distinguishes the two 429s from each other', async () => {
    // `rate_limited` and `daily_limit_reached` share a status code and mean
    // completely different things: wait a minute, versus come back tomorrow.
    vi.stubGlobal('fetch', answers(errorBody('daily_limit_reached', 'Limit reached.'), { status: 429 }))

    const result = await scanUrl('https://example.com')

    if (result.ok) throw new Error('expected failure')
    expect(result.error.code).toBe('daily_limit_reached')
  })
})

describe('failures that never reach the backend', () => {
  it('reports a refused connection as a network error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))

    const result = await scanUrl('https://example.com')

    if (result.ok) throw new Error('expected failure')
    expect(result.error.code).toBe('network_error')
    expect(result.error.status).toBeNull()
    expect(result.error.message).toMatch(/could not reach/i)
  })

  it('reports an HTML error page as malformed rather than crashing', async () => {
    // What a sleeping host or a proxy in front of the backend actually sends.
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response('<html><body>502 Bad Gateway</body></html>', {
          status: 502,
          headers: { 'Content-Type': 'text/html' },
        }),
      ),
    )

    const result = await scanUrl('https://example.com')

    if (result.ok) throw new Error('expected failure')
    expect(result.error.code).toBe('malformed_response')
    expect(result.error.status).toBe(502)
  })

  it('reports JSON that is not the contract shape as malformed', async () => {
    // Rule 7: the backend never returns a bare array at the top level, so
    // this means something other than the backend answered.
    vi.stubGlobal('fetch', answers(['unexpected'], { status: 400 }))

    const result = await scanUrl('https://example.com')

    if (result.ok) throw new Error('expected failure')
    expect(result.error.code).toBe('malformed_response')
  })

  it('gives up rather than hanging forever', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init: RequestInit) =>
        // A backend that accepts the connection and then goes quiet. Without
        // our own timeout this would hang until the browser gave up, which
        // can be minutes of a blank screen.
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener('abort', () => reject(new Error('aborted')))
        }),
      ),
    )

    const pending = scanUrl('https://example.com')
    await vi.advanceTimersByTimeAsync(95_000)
    const result = await pending

    if (result.ok) throw new Error('expected failure')
    expect(result.error.code).toBe('request_timeout')
  })

  it('re-throws a cancellation, which is not a failure to report', async () => {
    const controller = new AbortController()
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener('abort', () => reject(new Error('aborted')))
        }),
      ),
    )

    const pending = scanUrl('https://example.com', { signal: controller.signal })
    controller.abort()

    await expect(pending).rejects.toThrow()
  })
})

describe('verifyCode', () => {
  it('posts to /verify with the code being checked', async () => {
    vi.stubGlobal('fetch', answers({ ok: true }))

    const result = await verifyCode('the-right-code')

    expect(result.ok).toBe(true)
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe(`${BASE}/verify`)
    expect(init.method).toBe('POST')
    expect(init.headers['X-Access-Code']).toBe('the-right-code')
  })

  it('returns unauthorized for a wrong code, which is an answer and not a fault', async () => {
    vi.stubGlobal('fetch', answers(errorBody('unauthorized', 'That access code is not right.'), { status: 401 }))

    const result = await verifyCode('wrong')

    if (result.ok) throw new Error('expected failure')
    expect(result.error.code).toBe('unauthorized')
    // Task 8.0 needs to tell "your code is wrong" from "the backend is
    // asleep", because only one of them is worth retyping a code over.
    expect(result.error.code).not.toBe('network_error')
  })
})

describe('checkHealth', () => {
  it('reads the version, which tells a sleeping backend from a broken one', async () => {
    vi.stubGlobal('fetch', answers({ status: 'ok', version: '0.1.0' }))

    const result = await checkHealth()

    if (!result.ok) throw new Error('expected success')
    expect(result.data.version).toBe('0.1.0')
  })

  it('is a GET and carries no body', async () => {
    vi.stubGlobal('fetch', answers({ status: 'ok', version: '0.1.0' }))

    await checkHealth()

    const [, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(init.method).toBe('GET')
    expect(init.body).toBeUndefined()
  })
})
