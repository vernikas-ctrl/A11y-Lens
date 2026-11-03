/**
 * What a scan looks like while it is happening. Task 8.4.
 *
 * A scan takes about four seconds against a warm backend and considerably
 * longer against one that has been asleep, because a free host has to start
 * the process and launch Chromium before any of our code runs. Silence for
 * that long reads as breakage, and the second thing somebody does when a page
 * seems broken is press the button again.
 *
 * Two deliberate choices.
 *
 * **It says what is happening, not just that something is.** A spinner is a
 * promise with no content. "Opening the page", then "Checking it against the
 * accessibility rules", tells somebody roughly where they are and makes the
 * wait feel accounted for.
 *
 * **It is honest about not knowing.** There is no percentage bar, because a
 * percentage would be invented -- the backend reports nothing until it is
 * finished. The stages advance on a timer that matches the typical shape of a
 * scan, and the last one says so rather than pretending to stall at 90%.
 */

import { useEffect, useState } from 'react'

/** Roughly how a scan actually spends its time, from Phase 1's measurements. */
const STAGES: ReadonlyArray<{ after: number; says: string }> = [
  { after: 0, says: 'Opening the page…' },
  { after: 3_000, says: 'Checking it against the accessibility rules…' },
  { after: 8_000, says: 'Still going. A slow page, or the server waking up…' },
  { after: 25_000, says: 'This is taking longer than usual. It has not failed yet.' },
]

interface Props {
  /** Shown so the person can see which page they are waiting on. */
  url: string
  onCancel?: () => void
}

export default function ScanProgress({ url, onCancel }: Props) {
  const [stage, setStage] = useState(0)

  useEffect(() => {
    const timers = STAGES.slice(1).map((s, index) =>
      setTimeout(() => setStage(index + 1), s.after),
    )
    return () => timers.forEach(clearTimeout)
  }, [])

  return (
    <div className="rounded-md border border-surface bg-surface p-4">
      {/* role="status" and polite: a scan finishing is worth announcing, but
          interrupting whatever a screen reader is already saying every time
          the stage changes would be worse than useless. */}
      <p role="status" aria-live="polite" className="font-medium text-ink">
        {STAGES[stage].says}
      </p>

      <p className="mt-1 break-all text-sm text-muted">{url}</p>

      {/* An indeterminate progressbar: it has no value, which is the accurate
          thing to say. aria-valuenow is deliberately absent rather than set
          to a number nobody measured. */}
      <div
        role="progressbar"
        aria-label="Scan in progress"
        className="mt-3 h-1 overflow-hidden rounded bg-paper"
      >
        {/* `motion-safe:` so the pulse stops entirely for anybody who has
            asked their system for reduced motion. Vestibular disorders make
            looping animation genuinely unpleasant, and a progress indicator
            is exactly the thing somebody has to sit and look at. The bar
            still shows, it just does not move. Task 9.6 covers the rest of
            the app; this one is here because it shipped with this change. */}
        <div className="h-full w-1/3 motion-safe:animate-pulse bg-primary" />
      </div>

      <p className="mt-3 text-sm text-muted">
        A scan usually takes a few seconds. The first one after a quiet period
        takes longer, because the server has to wake up.
      </p>

      {onCancel && (
        <button
          type="button"
          onClick={onCancel}
          className="mt-3 rounded-md border border-muted px-3 py-1 text-sm font-medium text-ink"
        >
          Stop waiting
        </button>
      )}
    </div>
  )
}
