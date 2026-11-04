/**
 * A11y-Lens scanned by A11y-Lens. Task 9.5.
 *
 * An accessibility tool that fails its own check is the one bug this project
 * cannot ship, and the existing proof was me running axe in a browser by hand
 * and reporting the result. That is exactly the kind of check that quietly
 * stops happening. This one fails the build instead.
 *
 * **It uses the scanner's own axe**, imported straight out of
 * `backend/app/vendor/axe-core/`, rather than a second copy from npm. One
 * version in the repository, upgraded in one place, and the frontend is
 * tested by literally the same engine that tests everybody else's pages. If
 * the two ever disagreed, the demo report would be describing a different
 * axe from the one that produced it.
 *
 * **`color-contrast` is turned off here, and covered properly elsewhere.**
 * jsdom does not lay out or paint, so every colour comes back as a
 * computed-style default and axe cannot judge any of it. Leaving the rule on
 * would produce either false passes or noise, both worse than nothing.
 * `palette.test.ts` does the WCAG arithmetic on the real colour values
 * instead, which is task 9.4 and does not need a browser at all.
 */

import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AXE_SOURCE from '../../backend/app/vendor/axe-core/axe.min.js?raw'
import App from './App'
import AccessGate from './access/AccessGate'
import { storeCode } from './access/storage'
import { demoReport } from './demo/demoReport'
import ReportView from './report/ReportView'

/**
 * Just the parts of axe's API this file touches, declared here.
 *
 * The alternative is a devDependency on `axe-core` purely for its types,
 * which would put a second copy of axe in the repository at a version that
 * could drift from the vendored one. A dozen lines of interface is cheaper
 * than that, and the version assertion below catches any drift anyway.
 */
interface AxeViolation {
  id: string
  impact: string | null
  nodes: ReadonlyArray<{ target: string[] }>
}

interface AxeResults {
  violations: AxeViolation[]
  passes: unknown[]
  testEngine: { name: string; version: string }
}

interface AxeRunOptions {
  runOnly?: { type: 'tag'; values: string[] }
  rules?: Record<string, { enabled: boolean }>
}

interface AxeGlobal {
  run: (context: Element | Document, options: AxeRunOptions) => Promise<AxeResults>
}

/** Evaluate the vendored bundle once, into this test file's window. */
function loadAxe(): AxeGlobal {
  const existing = (window as unknown as { axe?: AxeGlobal }).axe
  if (existing) return existing
  // eslint-disable-next-line no-new-func
  new Function(AXE_SOURCE).call(window)
  const axe = (window as unknown as { axe?: AxeGlobal }).axe
  if (!axe) throw new Error('the vendored axe-core did not define window.axe')
  return axe
}

const WCAG_AA = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

/** Runs axe over a container and returns the violations, as readable strings. */
async function violationsIn(container: Element): Promise<string[]> {
  const axe = loadAxe()
  const results = await axe.run(container, {
    runOnly: { type: 'tag', values: WCAG_AA },
    // See the note at the top: jsdom cannot paint, so this rule has nothing
    // real to measure. palette.test.ts covers it with arithmetic.
    rules: { 'color-contrast': { enabled: false } },
  })
  return results.violations.map(
    (violation: AxeViolation) =>
      `${violation.id} (${violation.impact}) on ${violation.nodes.length}: ` +
      `${violation.nodes[0]?.target.join(' ')}`,
  )
}

/** A fetch stub that keeps the gate open without a backend. */
function backendSaysYes() {
  return vi.fn(async (url: string) => {
    const body = url.includes('/health') ? { status: 'ok', version: '0.1.0' } : { valid: true }
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
}

beforeEach(() => {
  window.sessionStorage.clear()
  vi.stubGlobal('fetch', backendSaysYes())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.sessionStorage.clear()
  window.document.body.innerHTML = ''
})

describe('every screen passes our own scanner', () => {
  it('the access code screen', async () => {
    // The screen nobody can skip, and the first one Phase 9 looks at.
    const { container } = render(
      <AccessGate>
        <p>the application</p>
      </AccessGate>,
    )

    expect(await violationsIn(container)).toEqual([])
  })

  it('the report, which is most of the app', async () => {
    const { container } = render(
      <ReportView report={demoReport} explanationsAreHandWritten />,
    )

    expect(await violationsIn(container)).toEqual([])
  })

  it('a report with no findings at all', async () => {
    const clean = {
      ...demoReport,
      summary: { critical: 0, serious: 0, moderate: 0, minor: 0, total: 0 },
      issues: [],
    }
    const { container } = render(
      <ReportView report={clean} explanationsAreHandWritten={false} />,
    )

    expect(await violationsIn(container)).toEqual([])
  })

  it('a report whose explanations could not be fetched', async () => {
    // Contract 2.3's degraded mode. A different branch renders, so it is a
    // different page as far as axe is concerned.
    const degraded = {
      ...demoReport,
      explanations_available: false,
      explanations_unavailable_reason: 'api_unavailable' as const,
      issues: demoReport.issues.map((issue) => ({ ...issue, explanation: null, fix: null })),
    }
    const { container } = render(
      <ReportView report={degraded} explanationsAreHandWritten={false} />,
    )

    expect(await violationsIn(container)).toEqual([])
  })

  it('the whole application behind an open gate', async () => {
    // A remembered code, so the gate confirms it and gets out of the way.
    storeCode('a-remembered-code')
    const { container, findByLabelText } = render(
      <AccessGate>
        <App />
      </AccessGate>,
    )
    await findByLabelText(/address of the page to scan/i)

    expect(await violationsIn(container)).toEqual([])
  })

  it('a scan in progress', async () => {
    // Never-resolving fetch, so the progress panel is what is on screen.
    const user = userEvent.setup()
    const { container, findByLabelText, findByRole } = render(<App />)

    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})))
    await user.type(await findByLabelText(/address of the page/i), 'https://example.com')
    await user.click(await findByRole('button', { name: 'Scan' }))
    await findByRole('progressbar')

    expect(await violationsIn(container)).toEqual([])
  })

  it('a failed scan', async () => {
    const user = userEvent.setup()
    const { container, findByLabelText, findByRole } = render(<App />)

    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ error: { code: 'unreachable', message: 'No.', detail: 'DNS' } }),
      { status: 502, headers: { 'Content-Type': 'application/json' } },
    )))
    await user.type(await findByLabelText(/address of the page/i), 'https://example.com')
    await user.click(await findByRole('button', { name: 'Scan' }))
    await findByRole('alert')

    expect(await violationsIn(container)).toEqual([])
  })
})

describe('the check itself', () => {
  it('is running the same axe the scanner uses', async () => {
    // If this ever drifts, the demo report would be describing findings from
    // a different engine than the one that produced it.
    const axe = loadAxe()
    const results = await axe.run(document.body, {
      runOnly: { type: 'tag', values: WCAG_AA },
    })
    expect(results.testEngine.version).toBe('4.14.0')
  })

  it('actually bites: a missing label is caught', async () => {
    // Task 9.5's "done when", as a test rather than a promise. If this one
    // ever passes, every assertion above it is worthless.
    const { container } = render(
      <form>
        <input type="text" />
      </form>,
    )

    const found = await violationsIn(container)
    expect(found.join(' ')).toMatch(/label/i)
  })
})
