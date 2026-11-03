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

/**
 * Every component's source, as text.
 *
 * A glob rather than a list of imports, so a component added later is
 * covered without anybody remembering to add it here -- which is the usual
 * way a rule like this stops being true.
 *
 * Test files are excluded. They quote the very patterns these rules forbid,
 * in order to assert that the real components do not use them, and a check
 * that fails because a test mentioned the thing it is testing is a check
 * nobody will trust for long.
 */
const APP_SOURCE = Object.values(
  import.meta.glob(['./**/*.tsx', '!./**/*.test.tsx'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }),
).join(' ')

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

function channels(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [0, 2, 4].map((i) => Number.parseInt(h.slice(i, i + 2), 16)) as [number, number, number]
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
  // Task 9.4. The states the task names as the usual failures, now that the
  // screens they appear on actually exist.
  ['muted', 'paper', 'placeholder text in the address box'],
  ['paper', 'muted', 'the label of a disabled button while a scan runs'],
  ['muted', 'surface', 'the text in a disabled input while a scan runs'],
]

/**
 * What a colour becomes when the element carrying it is drawn at less than
 * full opacity over `paper`.
 *
 * Here because the first version of the disabled styling used Tailwind's
 * `disabled:opacity-60`, which fades the whole element -- background and
 * text together -- onto whatever is behind it. Measured rather than assumed,
 * it put the disabled Scan button at **2.90:1** and the disabled input at
 * **4.40:1**.
 *
 * WCAG 1.4.3 exempts disabled controls, so neither was a violation. They were
 * replaced anyway: the disabled button is the thing somebody looks at for the
 * fifteen seconds a scan takes, and "you are not allowed to read this while
 * you wait" is not what disabling a control is supposed to mean. The app now
 * names explicit disabled colours, and the test below keeps the old approach
 * from creeping back.
 */
function composite(hex: string, over: string, alpha: number): string {
  const [fr, fg, fb] = channels(hex)
  const [br, bg, bb] = channels(over)
  const mix = (f: number, b: number) => Math.round(alpha * f + (1 - alpha) * b)
  return `#${[mix(fr, br), mix(fg, bg), mix(fb, bb)]
    .map((v) => v.toString(16).padStart(2, '0'))
    .join('')}`
}

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

describe('the states task 9.4 calls the usual failures', () => {
  it('does not fade disabled controls with opacity', () => {
    // `disabled:opacity-60` is the idiomatic Tailwind way and it is why this
    // test exists: it measured 2.90:1 on the Scan button. Explicit colours
    // replaced it, and this fails if the shortcut returns.
    expect(APP_SOURCE).not.toMatch(/disabled:opacity-/)
  })

  it('would have caught the opacity version', () => {
    // Proof the measurement above is real rather than remembered.
    const colours = palette()
    const faded = composite(colours.primary, colours.paper, 0.6)
    const measured = ratio(colours.paper, faded)

    expect(measured).toBeLessThan(AA_TEXT)
    expect(measured).toBeCloseTo(2.9, 1)
  })

  it('sets the placeholder colour rather than trusting the browser', () => {
    // Chrome's default placeholder is about #757575, which is 4.61:1 on
    // white -- a pass by six hundredths, and not the same grey everywhere.
    expect(CSS).toMatch(/::placeholder\s*\{[^}]*color:\s*var\(--color-muted\)/)
    // Firefox applies its own opacity on top of the colour, which would
    // quietly undo the measurement.
    expect(CSS).toMatch(/::placeholder\s*\{[^}]*opacity:\s*1/)
  })

  it('keeps the focus ring visible against both backgrounds', () => {
    // The ring is primary, drawn outside a white inner ring. 3:1 is the bar
    // for a user interface component rather than for text.
    const colours = palette()
    for (const background of ['paper', 'surface'] as const) {
      expect(ratio(colours.primary, colours[background])).toBeGreaterThanOrEqual(AA_LARGE)
    }
  })
})

describe('motion, task 9.6', () => {
  it('guards every animation behind motion-safe', () => {
    // A looping animation is genuinely unpleasant with a vestibular
    // disorder, and the one animation in this app is on a progress bar --
    // the thing somebody has to sit and watch. Tailwind's `animate-*` does
    // not consult prefers-reduced-motion on its own; `motion-safe:` is what
    // does that. This fails if an unguarded one is ever added.
    const unguarded = [...APP_SOURCE.matchAll(/(\S*)animate-[a-z-]+/g)]
      .map((match) => match[0])
      .filter((found) => !found.includes('motion-safe:'))

    expect(unguarded).toEqual([])
  })

  it('does not scroll the page smoothly without being asked', () => {
    // Smooth scrolling is motion too, and it is applied globally when it is
    // applied at all, so it is worth asserting it is absent rather than
    // discovering it later.
    expect(CSS).not.toMatch(/scroll-behavior:\s*smooth/)
  })
})
