/**
 * Rendering a report. Tasks 8.1, 8.5, 8.6 and 8.7.
 *
 * Several of these assert rules from `docs/api-contract.md` section 4 rather
 * than anything about this component's design. Those rules are promises about
 * what a reader sees, so the only place they can actually be kept is here --
 * and the only place they can be checked is a test like this.
 */

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Issue, Report, Severity } from '../api/types'
import { demoReport } from '../demo/demoReport'
import ReportView from './ReportView'

function issue(overrides: Partial<Issue> = {}): Issue {
  return {
    id: 'image-alt-0',
    rule_id: 'image-alt',
    severity: 'serious',
    wcag: ['1.1.1'],
    reference_url: 'https://dequeuniversity.com/rules/axe/4.10/image-alt',
    selector: 'main > img',
    html: '<img src="/logo.png">',
    explanation: { what: 'No alt attribute.', who: 'Screen reader users hear nothing.' },
    fix: { language: 'html', snippet: '<img src="/logo.png" alt="Logo">', assumptions: [] },
    ...overrides,
  }
}

function report(issues: Issue[], overrides: Partial<Report> = {}): Report {
  const counts: Record<Severity, number> = { critical: 0, serious: 0, moderate: 0, minor: 0 }
  for (const i of issues) counts[i.severity] += 1
  return {
    url: 'https://example.com/',
    page_title: 'Example Domain',
    scanned_at: '2026-11-03T10:30:00Z',
    scan_duration_ms: 4812,
    explanations_available: true,
    summary: { ...counts, total: issues.length },
    issues,
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('grouping and order', () => {
  it('puts the worst first, whatever order they arrived in', () => {
    render(
      <ReportView
        report={report([
          issue({ id: 'a', severity: 'minor' }),
          issue({ id: 'b', severity: 'critical' }),
          issue({ id: 'c', severity: 'moderate' }),
          issue({ id: 'd', severity: 'serious' }),
        ])}
      />,
    )

    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    expect(headings[0]).toMatch(/critical/)
    expect(headings[1]).toMatch(/serious/)
    expect(headings[2]).toMatch(/moderate/)
    expect(headings[3]).toMatch(/minor/)
  })

  it('counts each group', () => {
    render(
      <ReportView
        report={report([
          issue({ id: 'a', severity: 'critical' }),
          issue({ id: 'b', severity: 'critical' }),
          issue({ id: 'c', severity: 'minor' }),
        ])}
      />,
    )

    expect(screen.getByRole('heading', { name: /critical/ })).toHaveTextContent('2 problems')
    expect(screen.getByRole('heading', { name: /minor/ })).toHaveTextContent('1 problem')
  })

  it('leaves out levels with nothing in them', () => {
    // An empty "0 moderate" heading is noise, and on a long report it is
    // noise a screen-reader user has to walk past.
    render(<ReportView report={report([issue({ severity: 'critical' })])} />)

    expect(screen.queryByRole('heading', { name: /moderate/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /minor/ })).not.toBeInTheDocument()
  })

  it('gives each group its own heading so they can be jumped between', () => {
    render(
      <ReportView
        report={report([issue({ id: 'a', severity: 'critical' }), issue({ id: 'b', severity: 'minor' })])}
      />,
    )

    // Navigating by heading is how a screen reader user skims. Two groups
    // means two level-3 headings, not one list with visual separators -- and
    // the issue cards inside them step down to h4, so they are not counted
    // here. This assertion originally found four, which was the component
    // committing `heading-order`, one of the faults it reports.
    expect(screen.getAllByRole('heading', { level: 3 })).toHaveLength(2)
  })
})

describe('severity is never carried by colour alone', () => {
  it.each(['critical', 'serious', 'moderate', 'minor'] as const)(
    'names %s in words',
    (severity) => {
      render(<ReportView report={report([issue({ severity })])} />)

      // WCAG 1.4.1. Roughly one man in twelve cannot reliably tell the red
      // from the grey, and an accessibility tool failing this would be a
      // poor advertisement.
      expect(screen.getByRole('heading', { name: new RegExp(severity) })).toBeVisible()
    },
  )

  it('explains what each level means rather than assuming the word is enough', () => {
    render(<ReportView report={report([issue({ severity: 'serious' })])} />)

    // Appears on the group and again on each card, deliberately: somebody
    // who arrives at one finding has not read the group heading above it.
    expect(screen.getAllByText(/much harder to use/i).length).toBeGreaterThan(0)
  })
})

describe('one issue, read end to end', () => {
  it('shows what is wrong and who it affects', () => {
    render(<ReportView report={report([issue()])} />)

    expect(screen.getByText('No alt attribute.')).toBeVisible()
    expect(screen.getByText(/screen reader users hear nothing/i)).toBeVisible()
  })

  it('shows where it is', () => {
    render(<ReportView report={report([issue()])} />)

    expect(screen.getByText('main > img')).toBeVisible()
    expect(screen.getByText('<img src="/logo.png">')).toBeVisible()
  })

  it('shows the corrected code and a way to copy it', () => {
    render(<ReportView report={report([issue()])} />)

    expect(screen.getByText('<img src="/logo.png" alt="Logo">')).toBeVisible()
    expect(screen.getByRole('button', { name: /copy/i })).toBeVisible()
  })

  it('links to the rule, saying where it goes and that it leaves the page', () => {
    render(<ReportView report={report([issue()])} />)

    const link = screen.getByRole('link', { name: /image-alt/ })
    expect(link).toHaveAttribute('href', 'https://dequeuniversity.com/rules/axe/4.10/image-alt')
    expect(link).toHaveAccessibleName(/new tab/i)
    // noreferrer as well as noopener: on a link-only app, the referrer is the
    // link itself.
    expect(link).toHaveAttribute('rel', expect.stringContaining('noreferrer'))
  })

  it('names the copy button for the issue it belongs to', async () => {
    // Six findings means six buttons saying "Copy". Heard out of context,
    // that is six identical buttons.
    render(
      <ReportView
        report={report([
          issue({ id: 'a', rule_id: 'image-alt' }),
          issue({ id: 'b', rule_id: 'button-name' }),
        ])}
      />,
    )

    expect(screen.getByRole('button', { name: /image-alt/ })).toBeVisible()
    expect(screen.getByRole('button', { name: /button-name/ })).toBeVisible()
  })
})

describe('the assumptions are shown as assumptions', () => {
  const guessing = issue({
    fix: {
      language: 'html',
      snippet: '<img src="/logo.png" alt="Acme Corp logo">',
      assumptions: ['Assumed this is the Acme Corp logo, from the filename.'],
    },
  })

  it('shows them beside the snippet', () => {
    render(<ReportView report={report([guessing])} />)

    expect(screen.getByText(/assumed this is the acme corp logo/i)).toBeVisible()
  })

  it('does not hide them behind a disclosure', () => {
    // Contract rule 5, verbatim: not collapsed, not a tooltip. Somebody
    // copying the snippet has to pass their eyes over this to reach it.
    const { container } = render(<ReportView report={report([guessing])} />)

    expect(container.querySelector('details')).toBeNull()
    expect(screen.getByText(/assumed this is the acme corp logo/i)).toBeVisible()
  })

  it('says how many there are, so none is missed', () => {
    render(
      <ReportView
        report={report([
          issue({
            fix: { language: 'html', snippet: '<p>x</p>', assumptions: ['One.', 'Two.', 'Three.'] },
          }),
        ])}
      />,
    )

    expect(screen.getByText(/makes 3 assumptions/i)).toBeVisible()
  })

  it('uses the singular for one', () => {
    render(<ReportView report={report([guessing])} />)

    expect(screen.getByText(/makes one assumption/i)).toBeVisible()
  })

  it('says nothing at all when the fix involved no guessing', () => {
    // An empty "assumptions" box on a mechanical fix would train people to
    // ignore the box, which is the one thing it must not do.
    render(<ReportView report={report([issue()])} />)

    expect(screen.queryByText(/assumption/i)).not.toBeInTheDocument()
  })
})

describe('when explanations are unavailable', () => {
  const bare = report(
    [issue({ explanation: null, fix: null })],
    { explanations_available: false, explanations_unavailable_reason: 'daily_limit_reached' },
  )

  it('still shows the finding', () => {
    render(<ReportView report={bare} />)

    expect(screen.getByText('<img src="/logo.png">')).toBeVisible()
    expect(screen.getByRole('heading', { name: /serious/ })).toBeVisible()
  })

  it('says why, without calling it an error', () => {
    render(<ReportView report={bare} />)

    expect(screen.getByText(/resets tomorrow/i)).toBeVisible()
    expect(screen.getByText(/every finding below is still real/i)).toBeVisible()
  })

  it('distinguishes the daily limit from the service being down', () => {
    render(
      <ReportView
        report={report([issue({ explanation: null, fix: null })], {
          explanations_available: false,
          explanations_unavailable_reason: 'api_unavailable',
        })}
      />,
    )

    expect(screen.getByText(/could not be reached/i)).toBeVisible()
    expect(screen.queryByText(/resets tomorrow/i)).not.toBeInTheDocument()
  })

  it('offers no copy button, because there is nothing to copy', () => {
    render(<ReportView report={bare} />)

    expect(screen.queryByRole('button', { name: /copy/i })).not.toBeInTheDocument()
  })
})

describe('the saved demo report', () => {
  it('renders in full with no backend call whatsoever', () => {
    // Task 8.1's "done when". `fetch` is replaced with something that throws,
    // so a component reaching for the network fails the test rather than
    // quietly succeeding because the backend happened to be up.
    vi.stubGlobal('fetch', vi.fn(() => { throw new Error('the demo must not call the backend') }))

    render(<ReportView report={demoReport} explanationsAreHandWritten />)

    expect(screen.getByRole('heading', { name: /6 problems found/i })).toBeVisible()
    expect(screen.getByRole('heading', { name: /critical/ })).toHaveTextContent('3 problems')
  })

  it('every finding carries an explanation and a fix', () => {
    // Contract rule 4: null together or populated together. A demo with a
    // hole in it would make tasks 8.6 and 8.7 look finished when they are not.
    for (const i of demoReport.issues) {
      expect(i.explanation, `${i.rule_id} has no explanation`).not.toBeNull()
      expect(i.fix, `${i.rule_id} has no fix`).not.toBeNull()
    }
  })

  it('says the explanations were written by hand', () => {
    render(<ReportView report={demoReport} explanationsAreHandWritten />)

    const notice = screen.getByText(/written by hand/i)
    expect(notice).toBeVisible()
    // And is clear that the findings themselves are not invented.
    expect(screen.getByText(/come\s+from a real scan/i)).toBeVisible()
  })

  it('says nothing about hand-writing for an ordinary report', () => {
    render(<ReportView report={report([issue()])} />)

    expect(screen.queryByText(/written by hand/i)).not.toBeInTheDocument()
  })

  it('every demo fix declares its assumptions', () => {
    // These are invented snippets. A demo that showed confident code with no
    // caveats would teach exactly the habit task 8.7 exists to prevent.
    for (const i of demoReport.issues) {
      expect(i.fix?.assumptions.length, `${i.rule_id} declares no assumptions`).toBeGreaterThan(0)
    }
  })
})

describe('copying', () => {
  it('confirms in a way a screen reader announces', async () => {
    // userEvent.setup() installs its own clipboard into jsdom, so this spies
    // on that rather than replacing `navigator` and fighting it.
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText')
    render(<ReportView report={report([issue()])} />)

    await user.click(screen.getByRole('button', { name: /copy/i }))

    expect(writeText).toHaveBeenCalledWith('<img src="/logo.png" alt="Logo">')
    const status = await screen.findByText('Copied')
    expect(status).toHaveAttribute('aria-live', 'polite')
  })

  it('says so when the clipboard refuses', async () => {
    // Insecure origins and some permission settings reject this. A button
    // that silently does nothing is worse than one that admits it failed,
    // because the person walks away believing they have the code.
    const user = userEvent.setup()
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('denied'))
    render(<ReportView report={report([issue()])} />)

    await user.click(screen.getByRole('button', { name: /copy/i }))

    expect(await screen.findByText(/ctrl\+c/i)).toBeVisible()
  })
})

describe('the report header', () => {
  it('names the page that was scanned', () => {
    render(<ReportView report={report([issue()])} />)

    const heading = screen.getByRole('heading', { level: 2 })
    expect(within(heading.parentElement!).getByText(/example\.com/)).toBeVisible()
  })

  it('copes with a page that has no title', () => {
    // Contract 2.1: page_title is null when the page has no <title>, which is
    // itself an accessibility problem and must not crash the thing reporting it.
    render(<ReportView report={report([issue()], { page_title: null })} />)

    expect(screen.getByRole('heading', { level: 2 })).toBeVisible()
    expect(screen.getByText(/example\.com/)).toBeVisible()
  })
})
