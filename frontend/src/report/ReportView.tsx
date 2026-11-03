/**
 * A whole report. Task 8.5.
 *
 * Grouped by severity, worst first, with a count per group. Each group is a
 * `<section>` with its own heading, so somebody navigating by headings can
 * jump straight to the critical ones instead of walking the whole list.
 *
 * The summary line at the top is a sentence rather than four coloured chips.
 * A row of numbers means nothing to somebody new, and chips would put the
 * severity information back into colour, which `severity.ts` explains is the
 * thing to avoid.
 */

import type { Report } from '../api/types'
import { countLabel, groupBySeverity, SEVERITY_MEANING } from './severity'
import IssueCard from './IssueCard'

interface Props {
  report: Report
  /**
   * Set for the saved demo report, whose explanations were written by hand
   * rather than generated. Shown to the reader, not kept as a note in the
   * source -- see demo/demoReport.ts.
   */
  explanationsAreHandWritten?: boolean
}

export default function ReportView({ report, explanationsAreHandWritten = false }: Props) {
  const groups = groupBySeverity(report.issues)
  const { total } = report.summary

  return (
    <section aria-labelledby="report-heading" className="flex flex-col gap-6">
      <div>
        <h2 id="report-heading" className="text-xl font-semibold text-ink">
          {total === 0 ? 'No problems found' : `${countLabel(total)} found`}
        </h2>

        <p className="mt-1 break-all text-sm text-muted">
          {report.page_title ? `${report.page_title} — ` : ''}
          {report.url}
        </p>

        {total > 0 && (
          <p className="mt-2 text-ink">
            {groups
              .map((group) => `${group.issues.length} ${group.severity}`)
              .join(', ')}
            . Worst first.
          </p>
        )}
      </div>

      {/* Task 8.9. Contract 2.1: an empty `issues` array means no *detectable*
          issues, which is not the same as an accessible page -- and this is
          the one screen where somebody is most likely to stop looking. The
          caveat is part of the result, not small print below it.

          The figure is not rhetorical. `backend/tests/fixtures/broken.html`
          carries a documented blind spot: a field named only by its
          placeholder, which axe-core passes outright. The scanner cannot see
          it, so a page built entirely that way would produce this screen. */}
      {total === 0 && (
        <div className="rounded-md border border-surface bg-surface p-4">
          <p className="text-ink">
            The automated checks found nothing to report on this page. That is a good
            sign and worth having.
          </p>
          <p className="mt-2 text-ink">
            <span className="font-medium">It is not a clean bill of health.</span>{' '}
            Automated tools find roughly a third of accessibility problems. Whether a
            link&rsquo;s text makes sense out of context, whether alt text describes the
            right thing, whether the page can actually be operated by keyboard in a
            sensible order — none of that can be judged by a machine.
          </p>
          <p className="mt-2 text-sm text-muted">
            The useful next steps are to try the page with the keyboard alone, and to
            turn on a screen reader and listen to it.
          </p>
        </div>
      )}

      {/* Contract 2.3. Not an error -- the findings are all real and the scan
          worked. Said plainly so nobody assumes the page is fine. */}
      {!report.explanations_available && (
        <p
          role="status"
          className="rounded-md border border-muted bg-surface p-3 text-sm text-ink"
        >
          <span className="font-medium">Explanations are not available for this scan.</span>{' '}
          {report.explanations_unavailable_reason === 'daily_limit_reached'
            ? "A11y-Lens has reached its daily limit. It resets tomorrow."
            : 'The explanation service could not be reached.'}{' '}
          Every finding below is still real.
        </p>
      )}

      {/* Task 8.1's honesty requirement. The whole point of showing
          assumptions is that people should not trust generated text blindly,
          so being vague about where this text came from would undercut it. */}
      {explanationsAreHandWritten && report.explanations_available && (
        <p className="rounded-md border border-muted bg-surface p-3 text-sm text-ink">
          <span className="font-medium">About this example:</span> the findings below come
          from a real scan. The explanations and suggested fixes were written by hand rather
          than generated, because this project has no API budget yet. A live scan produces
          them in the same shape.
        </p>
      )}

      {groups.map((group) => (
        <section key={group.severity} aria-labelledby={`group-${group.severity}`}>
          <h3
            id={`group-${group.severity}`}
            className={`text-lg font-semibold ${
              group.severity === 'critical' ? 'text-alert' : 'text-ink'
            }`}
          >
            {/* The word first and the colour second: the heading reads
                correctly with no colour at all. */}
            {group.severity} {'—'} {countLabel(group.issues.length)}
          </h3>
          <p className="mt-1 text-sm text-muted">{SEVERITY_MEANING[group.severity]}</p>

          <ul className="mt-3 flex flex-col gap-3">
            {group.issues.map((issue) => (
              <li key={issue.id}>
                <IssueCard issue={issue} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </section>
  )
}
