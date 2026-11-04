/**
 * What the page says while a scan is running. Task 10.5.
 *
 * Rendered directly rather than through `ScanPanel`, unlike the rest of the
 * scanning tests: what is being checked here is what the text does over two
 * and a half minutes, and that needs the clock under the test's control. A
 * panel driving a real `fetch` cannot have both.
 */

import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { REQUEST_TIMEOUT_MS } from '../config'
import ScanProgress from './ScanProgress'

/** Moves the fake clock, letting React flush what the timers caused. */
function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms)
  })
}

function says(): string {
  return screen.getByRole('status').textContent ?? ''
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('the wait', () => {
  it('says what is happening, not just that something is', () => {
    render(<ScanProgress url="https://example.com/" />)
    expect(says()).toMatch(/opening the page/i)
  })

  it('names how long it will wait, taken from the budget itself', () => {
    render(<ScanProgress url="https://example.com/" />)

    // 165 seconds, rounded up, in words. A number typed into the sentence
    // could outlive the budget it describes.
    expect(screen.getByText(/gives up after about three minutes/i)).toBeVisible()
    expect(REQUEST_TIMEOUT_MS).toBeLessThanOrEqual(3 * 60_000)
  })

  it('keeps saying something new, long after a scan would normally be done', () => {
    render(<ScanProgress url="https://example.com/" />)

    advance(3_000)
    const early = says()
    expect(early).toMatch(/accessibility rules/i)

    advance(22_000)
    const atTwentyFive = says()
    expect(atTwentyFive).not.toBe(early)

    // The point of the task. Before this, the 25-second message was the last
    // one there was, so with a budget of 165 seconds the page said exactly
    // the same thing for the remaining 140 -- which is what a frozen page
    // looks like.
    advance(55_000)
    expect(says()).not.toBe(atTwentyFive)
  })

  it('never claims to know how far through it is', () => {
    render(<ScanProgress url="https://example.com/" />)
    advance(90_000)

    // An indeterminate progressbar. A percentage would have to be invented:
    // the backend reports nothing at all until it has finished.
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow')
  })

  it('announces its changes politely rather than interrupting', () => {
    render(<ScanProgress url="https://example.com/" />)

    // Every stage change is announced through the same live region, so an
    // assertive one would talk over whatever a screen reader was saying --
    // four times, during a wait.
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite')
  })
})
