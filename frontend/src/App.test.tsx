/**
 * Task 7.3's trivial test, and a little more.
 *
 * The task asks for one passing test to prove the runner works. These also
 * check the two things that are cheapest to get right now and most annoying
 * to retrofit: exactly one top-level heading, and a landmark to put the
 * content in. Phase 9 audits this properly; starting correct is easier than
 * correcting later.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  it('renders', () => {
    render(<App />)

    expect(screen.getByRole('heading', { name: 'A11y-Lens' })).toBeVisible()
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

  it('gives its link a name that makes sense read on its own', () => {
    // Screen readers can list every link on a page. "Click here" in such a
    // list is useless, which is why the accessible name is what is asserted
    // here rather than the text content.
    render(<App />)

    const link = screen.getByRole('link')
    expect(link).toHaveAccessibleName(/github\.com/)
  })
})
