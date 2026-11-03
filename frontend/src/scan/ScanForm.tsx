/**
 * The URL input. Task 8.2.
 *
 * `type="url"` with `noValidate` on the form: the input type brings the right
 * keyboard on a phone, and `noValidate` turns off the browser's own bubble so
 * our message is the only one. The browser's bubble cannot be styled, is not
 * reliably announced, and disappears the moment the field is touched -- which
 * is three accessibility problems in a feature meant to help.
 */

import { useId, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { problemWith } from './urlInput'

interface Props {
  onScan: (url: string) => void
  busy: boolean
}

export default function ScanForm({ onScan, busy }: Props) {
  const [typed, setTyped] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  // Generated rather than hard-coded, so a second form on the page could not
  // produce two elements with the same id -- which would quietly break the
  // label's association with one of them.
  const inputId = useId()
  const problemId = `${inputId}-problem`

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const found = problemWith(typed)
    if (found !== null) {
      setProblem(found)
      // Put the cursor where the correction has to happen.
      inputRef.current?.focus()
      return
    }

    setProblem(null)
    onScan(typed)
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-2">
      <label htmlFor={inputId} className="font-medium text-ink">
        Address of the page to scan
      </label>

      <p className="text-sm text-muted">
        A public web page, like https://example.com. Pages behind a login cannot be
        scanned.
      </p>

      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          ref={inputRef}
          id={inputId}
          type="url"
          inputMode="url"
          value={typed}
          onChange={(event) => {
            setTyped(event.target.value)
            // Clearing as soon as they start fixing it: leaving a stale
            // complaint under a field somebody is actively correcting is
            // both wrong and irritating.
            if (problem !== null) setProblem(null)
          }}
          placeholder="https://example.com"
          autoComplete="url"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          disabled={busy}
          aria-describedby={problem ? problemId : undefined}
          aria-invalid={problem !== null}
          className="flex-1 rounded-md border border-muted bg-paper px-3 py-2 text-ink disabled:opacity-60"
        />

        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-primary px-4 py-2 font-medium text-paper disabled:opacity-60"
        >
          {busy ? 'Scanning…' : 'Scan'}
        </button>
      </div>

      {/* Present even when empty, so the live region exists before it has
          anything to say. One added at the same moment as its text is often
          not announced.

          `aria-live="assertive"` rather than `role="alert"`, which would mean
          the same thing to a screen reader but would put two elements with
          that role on screen whenever a scan has also failed. Two alert
          regions competing is worse for a screen reader than one, and it made
          the tests ambiguous -- which was the clue. The failure notice keeps
          the role; this is a field's own complaint and is reached through
          aria-describedby anyway. */}
      <p
        id={problemId}
        aria-live="assertive"
        aria-atomic="true"
        className="min-h-6 text-sm text-alert"
      >
        {problem}
      </p>
    </form>
  )
}
