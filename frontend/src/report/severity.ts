/**
 * How severity is ordered and named. Task 8.5.
 *
 * **Severity is a word, never only a colour.** Roughly one man in twelve
 * cannot reliably distinguish red from grey, so a list where the only thing
 * separating "critical" from "minor" is a hue is a list they cannot read.
 * This is also WCAG 1.4.1, and an accessibility tool failing it would be a
 * poor advertisement.
 *
 * Colour is allowed to reinforce the word. The palette in `index.css` has
 * exactly one colour for this -- `alert` -- and it marks the critical group
 * only, so it means "look here first" rather than carrying the information by
 * itself.
 */

import type { Severity } from '../api/types'

/** Worst first. axe-core's own scale, not a custom one. */
export const SEVERITY_ORDER: readonly Severity[] = ['critical', 'serious', 'moderate', 'minor']

/**
 * What each level means, in a sentence a non-specialist can act on.
 *
 * axe-core's own words are aimed at developers who already know the field --
 * "serious" and "moderate" do not tell somebody new what to fix first.
 */
export const SEVERITY_MEANING: Record<Severity, string> = {
  critical: 'Blocks people from using this part of the page at all.',
  serious: 'Makes this part of the page much harder to use.',
  moderate: 'Causes confusion or extra effort.',
  minor: 'Worth fixing, but unlikely to stop anybody.',
}

/** Sorts issues worst-first, keeping the backend's order within a level. */
export function bySeverity<T extends { severity: Severity }>(issues: readonly T[]): T[] {
  return [...issues].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity),
  )
}

/** Groups issues by level, worst first, leaving out levels with nothing in them. */
export function groupBySeverity<T extends { severity: Severity }>(
  issues: readonly T[],
): Array<{ severity: Severity; issues: T[] }> {
  return SEVERITY_ORDER.map((severity) => ({
    severity,
    issues: issues.filter((issue) => issue.severity === severity),
  })).filter((group) => group.issues.length > 0)
}

/** "1 problem" / "3 problems" -- small, and read by everyone. */
export function countLabel(n: number): string {
  return n === 1 ? '1 problem' : `${n} problems`
}
