/**
 * The page behind the access gate.
 *
 * Most of what App renders is tested in ReportView.test.tsx. What is left
 * here is the frame around it, and the structural things that are cheapest to
 * get right now and most annoying to retrofit in Phase 9.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  it('renders', () => {
    render(<App />)

    expect(screen.getByRole('heading', { name: 'A11y-Lens', level: 1 })).toBeVisible()
  })

  it('has exactly one level-one heading', () => {
    // A screen reader user navigates by headings. Two h1s, or none, makes the
    // page's structure a guess.
    render(<App />)

    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })

  it('puts its content in a main landmark', () => {
    // "Skip to main content" and every screen reader's landmark navigation
    // depend on this element existing.
    render(<App />)

    expect(screen.getByRole('main')).toBeInTheDocument()
  })

  it('never skips a heading level', () => {
    // `heading-order` is one of the six faults the demo report describes. An
    // accessibility tool committing it on the page where it describes it
    // would be hard to defend -- and this already caught one, where the
    // severity groups and the issue cards were both level 3.
    render(<App />)

    const levels = screen
      .getAllByRole('heading')
      .map((h) => Number(h.tagName.slice(1)))

    expect(levels[0]).toBe(1)
    for (let i = 1; i < levels.length; i += 1) {
      expect(
        levels[i] - levels[i - 1],
        `heading ${i} jumps from h${levels[i - 1]} to h${levels[i]}`,
      ).toBeLessThanOrEqual(1)
    }
  })

  it('shows the saved example report', () => {
    render(<App />)

    expect(screen.getByRole('heading', { name: /6 problems found/i })).toBeVisible()
  })

  it('says the example explanations were written by hand', () => {
    render(<App />)

    expect(screen.getByText(/written by hand/i)).toBeVisible()
  })

  it('carries the caveat about what automated tools can find', () => {
    // The README and task 8.9 both promise this. A tool that implies a clean
    // report means an accessible page is doing harm, and the demo page has a
    // documented blind spot proving the point.
    render(<App />)

    expect(screen.getByText(/roughly a third/i)).toBeVisible()
  })
})
