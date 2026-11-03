/**
 * Runs before every test file.
 *
 * `@testing-library/jest-dom` adds assertions that describe the DOM in the
 * words a person would use -- `toBeVisible`, `toHaveAccessibleName` -- rather
 * than in the words the DOM API uses. That matters more than usual here: this
 * app has to meet WCAG AA, and an assertion about an element's accessible
 * name tests the thing a screen reader actually announces, while an assertion
 * about its text content does not.
 */
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Without this, each test leaves its rendered components in the document and
// the next one's queries find two of everything. Testing Library used to do
// this automatically; it only does so when the test runner exposes globals,
// and this project turns those off.
afterEach(() => {
  cleanup()
})
