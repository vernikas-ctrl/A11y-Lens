/**
 * One finding, read end to end. Tasks 8.6 and 8.7.
 *
 * The order on screen is deliberate and is not the order of the JSON:
 *
 *   1. what is wrong        the finding
 *   2. who it affects       the reason to care
 *   3. where it is          selector and the offending HTML
 *   4. the corrected code   with its assumptions attached
 *   5. the reference        for anybody who wants the rule itself
 *
 * HEADING LEVELS step down from the severity group this card sits inside:
 * the group is an h3, so the card title is h4 and its sections are h5 and h6.
 * Getting this wrong is `heading-order`, which is one of the faults the demo
 * report itself reports -- an accessibility tool committing the error it is
 * describing would be hard to defend. A test counts the level-3 headings for
 * exactly this reason.
 *
 * "Who it affects" sits second because it is the part that persuades somebody
 * to act. A developer skimming a list of forty findings decides what to fix
 * from the consequence, not from the rule id -- which is also why
 * `docs/prompt.md` asks the model for `what` and `who` separately rather than
 * one paragraph.
 *
 * TASK 8.7 IS LOAD-BEARING HERE. `assumptions` is rendered immediately
 * beside the snippet, never collapsed, never behind a tooltip -- contract
 * rule 5 states this, and the reason is that a confidently wrong `alt`
 * attribute pasted in good faith is worse than a missing one, because it
 * looks finished and nobody checks it again.
 */

import type { Issue } from '../api/types'
import { SEVERITY_MEANING } from './severity'
import CodeBlock from './CodeBlock'

interface Props {
  issue: Issue
}

export default function IssueCard({ issue }: Props) {
  const { explanation, fix } = issue

  return (
    <article
      aria-labelledby={`${issue.id}-title`}
      className="rounded-md border border-surface bg-paper p-4"
    >
      <h4 id={`${issue.id}-title`} className="font-mono text-sm font-semibold text-ink">
        {issue.rule_id}
      </h4>

      <p className="mt-1 text-sm text-muted">
        {/* The severity word again, per issue. Somebody arriving by a link to
            one finding has not seen the group heading it came from. */}
        <span className="font-medium text-ink">{issue.severity}</span>
        {' — '}
        {SEVERITY_MEANING[issue.severity]}
        {issue.wcag.length > 0 && (
          <> {' · '} WCAG {issue.wcag.join(', ')}</>
        )}
      </p>

      {explanation === null ? (
        // Contract 2.3: explanation and fix are null together. Saying why
        // beats an empty space, and the findings are still worth having.
        <p className="mt-3 rounded border border-surface bg-surface p-3 text-sm text-muted">
          The plain-language explanation and the suggested fix are not available for this
          scan. The finding itself is unaffected.
        </p>
      ) : (
        <>
          <p className="mt-3 text-ink">{explanation.what}</p>
          <p className="mt-2 text-ink">
            <span className="font-medium">Who this affects: </span>
            {explanation.who}
          </p>
        </>
      )}

      <h5 className="mt-4 text-sm font-medium text-ink">Where it is</h5>
      <p className="mt-1 font-mono text-xs break-all text-muted">{issue.selector}</p>
      <pre
        tabIndex={0}
        className="mt-2 overflow-x-auto rounded-md border border-surface bg-surface px-3 py-2 text-sm text-ink"
      >
        <code>{issue.html}</code>
      </pre>

      {fix !== null && (
        <>
          <h5 className="mt-4 text-sm font-medium text-ink">Suggested fix</h5>

          <div className="mt-2">
            <CodeBlock
              code={fix.snippet}
              language={fix.language}
              label={`the suggested ${fix.language.toUpperCase()} fix for ${issue.rule_id}`}
            />
          </div>

          {fix.assumptions.length > 0 && (
            // Not a <details>, not a tooltip, not a colour-only warning. A
            // plain block directly under the code, because somebody copying
            // the snippet has to pass their eyes over this to reach it.
            <div className="mt-2 rounded-md border border-muted bg-surface p-3">
              <h6 className="text-sm font-medium text-ink">
                {fix.assumptions.length === 1
                  ? 'This fix makes one assumption'
                  : `This fix makes ${fix.assumptions.length} assumptions`}
              </h6>
              <p className="mt-1 text-sm text-muted">
                The scanner can see the code, not the intent. Check these before you use it.
              </p>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink">
                {fix.assumptions.map((assumption, index) => (
                  <li key={index}>{assumption}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      <p className="mt-4 text-sm">
        <a
          className="text-primary underline"
          href={issue.reference_url}
          target="_blank"
          // noreferrer as well as noopener: without it the linked page can
          // see where the visit came from, which on a deployed link-only app
          // is the link itself.
          rel="noopener noreferrer"
        >
          Read the full rule for {issue.rule_id}
          {/* Says where this goes and that it opens elsewhere, for anybody
              who hears links out of context rather than seeing them. */}
          <span className="sr-only"> (opens in a new tab, on dequeuniversity.com)</span>
        </a>
      </p>
    </article>
  )
}
