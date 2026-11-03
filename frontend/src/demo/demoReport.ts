/**
 * The saved demo report. Task 8.1.
 *
 * Imported as data, so it is part of the bundle and renders with the backend
 * switched off entirely. That is the point of it: the backend will live on a
 * free host that sleeps, and the first thing somebody sees after typing the
 * access code should not be a four-second wait followed by a cold-start
 * failure.
 *
 * **The findings are real and the explanations are not.** `report.json` is
 * genuine axe-core output from a real scan of `backend/tests/fixtures/
 * broken.html` -- same browser, same rules, same code path as a live scan.
 * The explanations and fixes were written by hand, because there is no API
 * budget, and `EXPLANATIONS_ARE_HAND_WRITTEN` below is what makes the UI say
 * so.
 *
 * The provenance lives here rather than as a field inside the JSON, because
 * the JSON is the contract's `Report` shape and nothing else. Adding a field
 * to it would mean the demo was no longer an example of what the backend
 * returns, which is most of its value.
 */

import type { Report } from '../api/types'
import report from './report.json'

export const demoReport: Report = report as Report

/**
 * Whether the explanations in the demo were written by a person.
 *
 * Shown to the reader rather than kept as a developer's note. Task 8.7 exists
 * because people should not paste generated code without reading what was
 * guessed; a tool that was vague about where its own demo text came from
 * would be teaching the opposite lesson. If an API key ever arrives, this
 * becomes false and the notice disappears on its own.
 */
export const EXPLANATIONS_ARE_HAND_WRITTEN = true

/** What the demo is a scan of, in words, for the page to show. */
export const DEMO_SUBJECT = 'a deliberately broken page built for this project'
