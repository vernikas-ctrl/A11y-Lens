/**
 * Code, with a button that copies it. Tasks 8.6 and 8.7.
 *
 * Two things here are less obvious than they look.
 *
 * **The copy button reports what happened.** `navigator.clipboard` can be
 * refused -- an insecure origin, a browser that has not seen a user gesture,
 * a permission denied -- and a button that silently does nothing is worse
 * than one that says it failed, because the person walks away believing they
 * have the code.
 *
 * **"Copied" is announced, not just shown.** The confirmation is a live
 * region, so a screen reader says it. A visual tick that nothing announces
 * tells a blind user nothing at all, and whether the copy worked is exactly
 * the thing they cannot otherwise check.
 */

import { useEffect, useRef, useState } from 'react'

type CopyState = 'idle' | 'copied' | 'failed'

interface Props {
  code: string
  /** `html` or `css`, shown as a label. Not used for highlighting yet. */
  language: string
  /** Names the button for screen readers, e.g. "corrected HTML for this image". */
  label: string
}

export default function CodeBlock({ code, language, label }: Props) {
  const [state, setState] = useState<CopyState>('idle')
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // Without this, a component unmounted between the copy and the reset leaves
  // a timer running against a component that is gone.
  useEffect(() => () => clearTimeout(timer.current), [])

  async function copy() {
    clearTimeout(timer.current)
    try {
      await navigator.clipboard.writeText(code)
      setState('copied')
    } catch {
      setState('failed')
    }
    timer.current = setTimeout(() => setState('idle'), 4000)
  }

  return (
    <div className="rounded-md border border-surface bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-paper px-3 py-2">
        <span className="font-mono text-xs uppercase tracking-wide text-muted">{language}</span>

        <div className="flex items-center gap-3">
          {/* Always present so the live region exists before it has anything
              to say -- one added at the same moment as its text is often not
              announced. */}
          <span role="status" aria-live="polite" className="text-xs text-muted">
            {state === 'copied' ? 'Copied' : state === 'failed' ? 'Press Ctrl+C to copy' : ''}
          </span>

          <button
            type="button"
            onClick={copy}
            // The visible word is just "Copy", which is ambiguous on a page
            // with six of these. The accessible name says which one.
            aria-label={`Copy ${label}`}
            className="rounded border border-muted px-2 py-1 text-xs font-medium text-ink"
          >
            Copy
          </button>
        </div>
      </div>

      {/* tabIndex makes the block focusable so it can be scrolled with the
          keyboard when the code is wider than the page. Without it, a
          keyboard user cannot reach the overflowing part at all. */}
      <pre
        tabIndex={0}
        className="overflow-x-auto px-3 py-3 text-sm text-ink"
      >
        <code>{code}</code>
      </pre>
    </div>
  )
}
