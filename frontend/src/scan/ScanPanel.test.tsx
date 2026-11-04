/**
 * Live scanning, end to end. Tasks 8.2, 8.4, 8.8 and 8.9.
 *
 * Driven through the panel rather than each component on its own, because
 * what these tasks promise is about sequence -- what is on screen while a
 * scan runs, what replaces it, and what is left when it fails. A test of
 * `ScanForm` alone cannot see any of that.
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Report } from '../api/types'
import { readStoredCode, storeCode } from '../access/storage'
import ScanPanel from './ScanPanel'

function report(overrides: Partial<Report> = {}): Report {
  return {
    url: 'https://example.com/',
    page_title: 'Example Domain',
    scanned_at: '2026-11-03T10:30:00Z',
    scan_duration_ms: 4812,
    explanations_available: true,
    summary: { critical: 1, serious: 0, moderate: 0, minor: 0, total: 1 },
    issues: [
      {
        id: 'image-alt-0',
        rule_id: 'image-alt',
        severity: 'critical',
        wcag: ['1.1.1'],
        reference_url: 'https://dequeuniversity.com/rules/axe/4.10/image-alt',
        selector: 'main > img',
        html: '<img src="/logo.png">',
        explanation: { what: 'No alt attribute.', who: 'Screen reader users.' },
        fix: { language: 'html', snippet: '<img alt="Logo">', assumptions: [] },
      },
    ],
    ...overrides,
  }
}

function answers(body: unknown, init: { status?: number; headers?: Record<string, string> } = {}) {
  return vi.fn(async (_url: string, _init: RequestInit) =>
    new Response(JSON.stringify(body), {
      status: init.status ?? 200,
      headers: { 'Content-Type': 'application/json', ...init.headers },
    }),
  )
}

function errorBody(code: string, message: string, detail: string | null = null) {
  return { error: { code, message, detail } }
}

/**
 * A response that is not the contract's shape at all. Task 10.5: this is what
 * a free host answers with while it is still starting -- its own error page,
 * in HTML, from the load balancer rather than from our app.
 */
function answersWithHtml(status: number) {
  return vi.fn(async (_url: string, _init: RequestInit) =>
    new Response('<html><body><h1>Service Unavailable</h1></body></html>', {
      status,
      headers: { 'Content-Type': 'text/html' },
    }),
  )
}

/** Fills the address box and submits. */
async function scan(user: ReturnType<typeof userEvent.setup>, url = 'https://example.com') {
  await user.type(screen.getByLabelText(/address of the page/i), url)
  await user.click(screen.getByRole('button', { name: 'Scan' }))
}

beforeEach(() => {
  window.sessionStorage.clear()
  vi.stubGlobal('fetch', answers(report()))
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.sessionStorage.clear()
})

describe('the form', () => {
  it('scans the address that was typed', async () => {
    const stub = answers(report())
    vi.stubGlobal('fetch', stub)
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user, 'https://example.com/page')

    await screen.findByRole('heading', { name: /1 problem found/i })
    expect(JSON.parse(stub.mock.calls[0][1].body as string)).toEqual({
      url: 'https://example.com/page',
    })
  })

  it('adds https:// when none was typed, because that is what people type', async () => {
    const stub = answers(report())
    vi.stubGlobal('fetch', stub)
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user, 'example.com')

    await screen.findByRole('heading', { name: /1 problem found/i })
    expect(JSON.parse(stub.mock.calls[0][1].body as string)).toEqual({
      url: 'https://example.com',
    })
  })

  it('refuses an empty address without calling the backend', async () => {
    // Task 8.2, verbatim: an inline message and no request.
    const stub = answers(report())
    vi.stubGlobal('fetch', stub)
    const user = userEvent.setup()
    render(<ScanPanel />)

    await user.click(screen.getByRole('button', { name: 'Scan' }))

    expect(await screen.findByText(/enter the address/i)).toBeVisible()
    expect(stub).not.toHaveBeenCalled()
  })

  it.each([
    ['not a web address at all', /does not look like a web address|missing its ending/i],
    ['ftp://example.com', /start with https/i],
    ['file:///etc/passwd', /start with https/i],
  ])('refuses %s without calling the backend', async (typed, expected) => {
    const stub = answers(report())
    vi.stubGlobal('fetch', stub)
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user, typed)

    expect(await screen.findByText(expected)).toBeVisible()
    expect(stub).not.toHaveBeenCalled()
  })

  it('clears the complaint as soon as the address is being corrected', async () => {
    // Leaving a stale complaint under a field somebody is actively fixing is
    // both wrong and irritating.
    const user = userEvent.setup()
    render(<ScanPanel />)

    await user.click(screen.getByRole('button', { name: 'Scan' }))
    const field = screen.getByLabelText(/address of the page/i)
    expect(field).toHaveAccessibleDescription(/enter the address/i)

    await user.type(field, 'h')

    await waitFor(() => expect(field).not.toHaveAccessibleDescription(/enter the address/i))
  })

  it('marks the field invalid and describes it with the message', async () => {
    const user = userEvent.setup()
    render(<ScanPanel />)

    await user.click(screen.getByRole('button', { name: 'Scan' }))

    const field = screen.getByLabelText(/address of the page/i)
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(field).toHaveAccessibleDescription(/enter the address/i)
  })
})

describe('while a scan is running', () => {
  function pending() {
    let release: (value: Response) => void = () => {}
    const stub = vi.fn(() => new Promise<Response>((resolve) => { release = resolve }))
    vi.stubGlobal('fetch', stub)
    return {
      finish: (body: unknown, status = 200) =>
        release(new Response(JSON.stringify(body), {
          status,
          headers: { 'Content-Type': 'application/json' },
        })),
    }
  }

  it('says what is happening, not merely that something is', async () => {
    // Task 8.4: a scan takes seconds and silence reads as breakage.
    pending()
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    expect(await screen.findByRole('status')).toHaveTextContent(/opening the page/i)
  })

  it('names the page being waited on', async () => {
    pending()
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user, 'https://example.com/slow')

    expect(await screen.findByText('https://example.com/slow')).toBeVisible()
  })

  it('offers a progress indicator that does not invent a percentage', async () => {
    // The backend reports nothing until it finishes, so any number would be
    // made up. aria-valuenow is deliberately absent.
    pending()
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    const bar = await screen.findByRole('progressbar')
    expect(bar).not.toHaveAttribute('aria-valuenow')
    expect(bar).toHaveAccessibleName(/scan in progress/i)
  })

  it('does not animate for anybody who asked for reduced motion', async () => {
    // Looping animation is genuinely unpleasant with a vestibular disorder,
    // and a progress indicator is the thing somebody has to sit and watch.
    pending()
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    const bar = await screen.findByRole('progressbar')
    const moving = bar.querySelector('[class*="animate-pulse"]')
    expect(moving?.className).toContain('motion-safe:')
  })

  it('disables the button so a scan cannot be started twice', async () => {
    const { finish } = pending()
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /scanning/i })).toBeDisabled(),
    )

    finish(report())
    await screen.findByRole('heading', { name: /1 problem found/i })
  })

  it('warns that a first scan after a quiet period is slower', async () => {
    // The backend is going on a host that sleeps. Somebody who does not know
    // that reads the wait as a fault.
    pending()
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    expect(await screen.findByText(/server has to wake up/i)).toBeVisible()
  })

  it('can be given up on', async () => {
    pending()
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)
    await user.click(await screen.findByRole('button', { name: /stop waiting/i }))

    await waitFor(() => expect(screen.queryByRole('progressbar')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Scan' })).toBeEnabled()
  })

  it('keeps the previous report on screen rather than blanking it', async () => {
    // Replacing a report with a spinner throws away something the person may
    // still be reading -- and if the new scan fails they are left with
    // nothing where they had a report.
    const user = userEvent.setup()
    render(<ScanPanel initialReport={report({ summary: { critical: 0, serious: 0, moderate: 0, minor: 0, total: 1 } })} />)

    expect(screen.getByRole('heading', { name: /1 problem found/i })).toBeVisible()

    const { finish } = pending()
    await scan(user)
    await screen.findByRole('progressbar')

    // The report is not shown during the scan, but it is not lost: cancelling
    // brings it straight back.
    await user.click(screen.getByRole('button', { name: /stop waiting/i }))
    expect(await screen.findByRole('heading', { name: /1 problem found/i })).toBeVisible()
    finish(report())
  })
})

describe('every way a scan can fail', () => {
  // Task 8.8 asks for seven. These are the contract's ten plus the three the
  // backend never sees, because a code with no case falls through to a bare
  // status number, which is the thing being avoided.
  it.each([
    ['invalid_url', 400, /missing letter or an extra space/i],
    ['blocked_address', 400, /home or office network/i],
    ['unreachable', 502, /behind a login/i],
    ['scan_timeout', 504, /simpler page on the same site/i],
    ['rate_limited', 429, /capped at a few per minute/i],
    ['daily_limit_reached', 429, /whole service rather than each person/i],
    ['internal_error', 500, /worth reporting/i],
    ['not_found', 404, /nothing you did caused this/i],
    ['method_not_allowed', 405, /nothing you did caused this/i],
  ])('%s says what to do next', async (code, status, advice) => {
    vi.stubGlobal('fetch', answers(errorBody(code, 'The backend said this.'), { status }))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    const alert = await screen.findByRole('alert')
    // Contract rule 1: the backend's message is shown as-is...
    expect(alert).toHaveTextContent('The backend said this.')
    // ...and the frontend adds what to do about it.
    expect(alert).toHaveTextContent(advice)
  })

it.each([
    ['blocked_address', 400, 'That address points inside a private network, so A11y-Lens will not scan it. This is deliberate, not a fault.'],
    ['unreachable', 502, 'That page could not be reached. Check the address is right and that the site is up.'],
    ['scan_timeout', 504, 'That page took too long to load. It may be unusually slow; it is worth trying again.'],
    ['daily_limit_reached', 429, 'A11y-Lens has reached its scan limit for today. It resets tomorrow.'],
    ['internal_error', 500, 'Something went wrong on our side. Sorry about that.'],
  ])('%s does not say the same thing twice', async (code, status, realMessage) => {
    // The advice is printed directly under the backend's own message, so
    // anything that repeats it reads as a stutter. The first live check
    // caught exactly that: the backend says "This is deliberate, not a
    // fault." and the advice said it again two lines later. The messages
    // below are the real ones from backend/app/errors.py.
    vi.stubGlobal('fetch', answers(errorBody(code, realMessage), { status }))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    const text = (await screen.findByRole('alert')).textContent ?? ''
    const sentences = text
      .split(/(?<=[.!?])\s+/)
      .map((sentence) => sentence.trim().toLowerCase())
      .filter((sentence) => sentence.length > 15)

    const seen = new Set<string>()
    for (const sentence of sentences) {
      expect(seen.has(sentence), `"${sentence}" appears twice`).toBe(false)
      seen.add(sentence)
    }
  })

  it('tells a sleeping backend from a broken one', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    expect(await screen.findByRole('alert')).toHaveTextContent(/waking up/i)
  })

  it('shows no raw status code without an explanation above it', async () => {
    // Task 8.8, verbatim: none of the seven shows a raw status code or an
    // empty screen.
    vi.stubGlobal('fetch', answers(errorBody('unreachable', 'Could not open that page.', 'DNS failure'), { status: 502 }))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Could not open that page.')
    // The status appears only inside the small detail line, after the words.
    const detail = within(alert).getByText(/detail:/i)
    expect(detail).toHaveTextContent('HTTP 502')
  })

  it('announces the failure rather than only showing it', async () => {
    // Somebody who submitted a scan and heard nothing is left watching a page
    // that never said anything.
    vi.stubGlobal('fetch', answers(errorBody('unreachable', 'Nope.'), { status: 502 }))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    expect(await screen.findByRole('alert')).toBeVisible()
  })

  it('offers a retry where retrying could help', async () => {
    vi.stubGlobal('fetch', answers(errorBody('scan_timeout', 'Too slow.'), { status: 504 }))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)
    expect(await screen.findByRole('button', { name: /try the scan again/i })).toBeVisible()

    vi.stubGlobal('fetch', answers(report()))
    await user.click(screen.getByRole('button', { name: /try the scan again/i }))

    expect(await screen.findByRole('heading', { name: /1 problem found/i })).toBeVisible()
  })

  it('does not offer a retry where it could not possibly help', async () => {
    // A blocked address will be blocked again. A button that cannot work is
    // worse than no button.
    vi.stubGlobal('fetch', answers(errorBody('blocked_address', 'Private network.'), { status: 400 }))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    await screen.findByRole('alert')
    expect(screen.queryByRole('button', { name: /try the scan again/i })).not.toBeInTheDocument()
  })

  it('passes the wait through on a rate limit', async () => {
    vi.stubGlobal(
      'fetch',
      answers(errorBody('rate_limited', 'Too many.'), { status: 429, headers: { 'Retry-After': '42' } }),
    )
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    expect(await screen.findByText(/try again in 42 seconds/i)).toBeVisible()
  })

  it('treats a host that is still starting as a wait, not a bug', async () => {
    // Task 10.5. This is the likeliest cold-start failure and it used to get
    // the worst answer: `client.ts` cannot parse an HTML error page, so it
    // becomes `malformed_response` -- which said "Worth reporting." and
    // offered no retry. Retrying is the only thing that fixes it, and
    // reporting it achieves nothing.
    vi.stubGlobal('fetch', answersWithHtml(503))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/still starting up|sleeps when nobody/i)
    expect(alert).not.toHaveTextContent(/worth reporting/i)
    expect(screen.getByRole('button', { name: /try the scan again/i })).toBeVisible()
  })

  it('still calls a malformed answer a bug when the status is not the host', async () => {
    // A 200 that is not the contract's shape is our mistake, not a sleeping
    // server. Somebody should hear about it, and trying again will not help.
    vi.stubGlobal('fetch', answersWithHtml(200))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/not something you did wrong/i)
    expect(alert).toHaveTextContent(/worth reporting/i)
    expect(screen.queryByRole('button', { name: /try the scan again/i })).not.toBeInTheDocument()
  })

  it('recovers when the woken host answers properly', async () => {
    vi.stubGlobal('fetch', answersWithHtml(503))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)
    await screen.findByRole('alert')

    // The second request lands on a container that has finished starting.
    vi.stubGlobal('fetch', answers(report()))
    await user.click(screen.getByRole('button', { name: /try the scan again/i }))

    expect(await screen.findByRole('heading', { name: /1 problem found/i })).toBeVisible()
  })
})

describe('when the access code stops working mid-session', () => {
  it('drops the stored code so the gate asks again', async () => {
    // The code was changed, or the backend restarted with a different one.
    // Carrying on would show a form that cannot work.
    storeCode('used-to-work')
    vi.stubGlobal('fetch', answers(errorBody('unauthorized', 'Not right.'), { status: 401 }))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    await screen.findByRole('alert')
    expect(readStoredCode()).toBeNull()
  })

  it('offers a way back to the code screen', async () => {
    vi.stubGlobal('fetch', answers(errorBody('unauthorized', 'Not right.'), { status: 401 }))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    expect(
      await screen.findByRole('button', { name: /enter the access code again/i }),
    ).toBeVisible()
  })
})

describe('a page with nothing wrong', () => {
  const clean = report({
    summary: { critical: 0, serious: 0, moderate: 0, minor: 0, total: 0 },
    issues: [],
  })

  it('says so clearly', async () => {
    vi.stubGlobal('fetch', answers(clean))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    expect(await screen.findByRole('heading', { name: /no problems found/i })).toBeVisible()
  })

  it('carries the caveat about what automated tools can find', async () => {
    // Task 8.9. Contract 2.1: empty means no *detectable* issues, not an
    // accessible page -- and this is the screen where somebody is most
    // likely to stop looking.
    vi.stubGlobal('fetch', answers(clean))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    expect(await screen.findByText(/not a clean bill of health/i)).toBeVisible()
    expect(screen.getAllByText(/roughly a third/i).length).toBeGreaterThan(0)
  })

  it('says what to actually do next', async () => {
    // A caveat with no next step leaves somebody knowing they are not
    // finished and not knowing what finishing looks like.
    vi.stubGlobal('fetch', answers(clean))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    expect(await screen.findByText(/keyboard alone/i)).toBeVisible()
    expect(screen.getByText(/screen reader/i)).toBeVisible()
  })

  it('is not mistaken for an error', async () => {
    vi.stubGlobal('fetch', answers(clean))
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    await screen.findByRole('heading', { name: /no problems found/i })
    expect(screen.queryByText(/scan failed/i)).not.toBeInTheDocument()
  })
})

describe('the demo report and a real one', () => {
  it('starts with the demo, labelled as hand-written', () => {
    render(<ScanPanel initialReport={report()} initialReportIsHandWritten />)

    expect(screen.getByText(/written by hand/i)).toBeVisible()
  })

  it('drops the hand-written notice once a real scan replaces it', async () => {
    // The notice is true of the demo and false of a live result. Leaving it
    // up would be a lie in the other direction.
    vi.stubGlobal('fetch', answers(report()))
    const user = userEvent.setup()
    render(<ScanPanel initialReport={report()} initialReportIsHandWritten />)

    expect(screen.getByText(/written by hand/i)).toBeVisible()
    await scan(user)

    await screen.findByRole('heading', { name: /1 problem found/i })
    await waitFor(() => expect(screen.queryByText(/written by hand/i)).not.toBeInTheDocument())
  })

  it('still shows the findings when explanations are unavailable', async () => {
    // Contract 2.3: a degraded scan is a success, not a failure.
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
    const user = userEvent.setup()
    render(<ScanPanel />)

    await scan(user)

    expect(await screen.findByRole('heading', { name: /1 problem found/i })).toBeVisible()
    expect(screen.queryByText(/scan failed/i)).not.toBeInTheDocument()
    expect(screen.getByText(/every finding below is still real/i)).toBeVisible()
  })
})
