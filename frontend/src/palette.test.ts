/**
 * The palette keeps its promises. Task 7.2.
 *
 * `src/index.css` carries a table of contrast ratios in a comment, and a
 * comment cannot fail. This can: it reads the colours out of the CSS and does
 * the WCAG arithmetic, so editing a colour to something that fails AA breaks
 * the build rather than quietly shipping.
 *
 * It reads the file rather than importing the values, because the file is
 * where the app gets them from. A second copy in TypeScript could agree with
 * this test and disagree with what renders.
 */

import { describe, expect, it } from 'vitest'
// `?raw` asks Vite for the file's text rather than its effect. Reading it
// with node:fs would work too, but would mean letting Node's types into a
// project that otherwise only targets the browser -- and then nothing would
// stop app code from importing a filesystem function that cannot exist there.
import CSS from './index.css?raw'

const AA_TEXT = 4.5
const AA_LARGE = 3.0

function palette(): Record<string, string> {
  const found: Record<string, string> = {}
  for (const match of CSS.matchAll(/--color-([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    found[match[1]] = match[2]
  }
  return found
}

function channel(value: number): number {
  const c = value / 255
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

function luminance(hex: string): number {
  const h = hex.replace('#', '')
  const [r, g, b] = [0, 2, 4].map((i) => Number.parseInt(h.slice(i, i + 2), 16))
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

function ratio(foreground: string, background: string): number {
  const [a, b] = [luminance(foreground), luminance(background)]
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

/** Every pair the app is allowed to use, and what each is for. */
const PAIRS: ReadonlyArray<readonly [string, string, string]> = [
  ['ink', 'paper', 'body text'],
  ['ink', 'surface', 'body text on cards'],
  ['muted', 'paper', 'secondary text, captions'],
  ['muted', 'surface', 'secondary text on cards'],
  ['primary', 'paper', 'links, focus ring'],
  ['primary', 'surface', 'links on cards'],
  ['paper', 'primary', 'button label'],
  ['alert', 'paper', 'error text'],
  ['alert', 'surface', 'error text on cards'],
  ['paper', 'alert', 'badge label'],
]

describe('the palette', () => {
  it('defines every colour the app refers to', () => {
    const colours = palette()
    for (const name of ['ink', 'muted', 'primary', 'alert', 'paper', 'surface']) {
      expect(colours, `--color-${name} is missing from index.css`).toHaveProperty(name)
    }
  })

  it.each(PAIRS)('%s on %s clears AA for normal text (%s)', (fg, bg) => {
    const colours = palette()
    const measured = ratio(colours[fg], colours[bg])
    expect(
      measured,
      `${fg} on ${bg} measures ${measured.toFixed(2)}:1, below the ${AA_TEXT} AA threshold`,
    ).toBeGreaterThanOrEqual(AA_TEXT)
  })

  it('leaves headroom above the threshold, not a squeak past it', () => {
    // Hover, disabled and pressed states are made by nudging these colours
    // lighter or darker. A pair that starts at 4.6:1 fails the moment it is
    // nudged, so the palette is required to start further up.
    const colours = palette()
    const worst = Math.min(...PAIRS.map(([fg, bg]) => ratio(colours[fg], colours[bg])))
    expect(worst).toBeGreaterThanOrEqual(5.5)
  })

  it('would catch a colour edited to something that fails', () => {
    // Proves the arithmetic bites rather than merely running. #9aa5ad on white
    // is about 2.3:1 -- a plausible-looking grey that is unreadable for many
    // people, and exactly the kind of value that gets picked by eye.
    expect(ratio('#9aa5ad', '#ffffff')).toBeLessThan(AA_TEXT)
    expect(ratio('#ffffff', '#ffffff')).toBeCloseTo(1, 5)
  })

  it('agrees with WCAG on the two anchor cases', () => {
    // Black on white is exactly 21:1 and white on white exactly 1:1. If the
    // formula above were wrong, these would be the first to show it.
    expect(ratio('#000000', '#ffffff')).toBeCloseTo(21, 5)
    expect(ratio('#767676', '#ffffff')).toBeGreaterThanOrEqual(AA_LARGE)
  })
})
