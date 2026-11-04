/**
 * The request budget. Task 10.5.
 *
 * The bug this task fixed was not a typo. It was two numbers in two languages
 * that nothing connected: the frontend gave up after 90 seconds, and the
 * backend could legitimately take 120. Fixing the arithmetic once does not
 * stop that happening again -- `SCAN_TIMEOUT_MS` and `EXPLAIN_TIMEOUT_MS` are
 * environment variables, changeable in the Cloud Run dashboard by somebody who
 * has never opened `src/config.ts`.
 *
 * So the two sides are tied together by a test, and it lives in the backend's
 * suite: `backend/tests/test_deploy_budget.py` reads this file and fails if
 * the ceilings here stop matching the ones it configures. It is there rather
 * than here for the reason `palette.test.ts` gives -- reading a file outside
 * this project would mean letting Node's types into a project that only
 * targets the browser, and then nothing would stop app code importing them.
 * Python reads a `.ts` file as text perfectly well.
 *
 * What is left here is this project's own behaviour: what the override does.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import { BACKEND_WORST_CASE_MS, REQUEST_TIMEOUT_MS } from './config'

describe('BACKEND_WORST_CASE_MS', () => {
  it('is the page-load budget twice plus the explanation budget once', () => {
    // 30s navigating, 30s again for the axe run, 60s explaining -- in series.
    // Missing the second one is what made the old 90s wrong.
    expect(BACKEND_WORST_CASE_MS).toBe(120_000)
  })
})

describe('REQUEST_TIMEOUT_MS', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
    vi.restoreAllMocks()
  })

  /** Re-imports config with the environment as currently stubbed. */
  async function reload() {
    vi.resetModules()
    return await import('./config')
  }

  it('leaves real headroom above the backend worst case by default', () => {
    // Equal would be no better than the bug: the backend's last millisecond of
    // budget is spent before Chromium has even been launched.
    expect(REQUEST_TIMEOUT_MS).toBeGreaterThan(BACKEND_WORST_CASE_MS)
  })

  it('takes an override above the backend worst case as given', async () => {
    vi.stubEnv('VITE_REQUEST_TIMEOUT_MS', '240000')
    const config = await reload()
    expect(config.REQUEST_TIMEOUT_MS).toBe(240_000)
  })

  it('refuses an override below the backend worst case, and says so', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.stubEnv('VITE_REQUEST_TIMEOUT_MS', '5000')
    const config = await reload()

    // Five seconds cannot catch a failure the backend has not had time to
    // produce. It can only report a working scan as broken.
    expect(config.REQUEST_TIMEOUT_MS).toBe(BACKEND_WORST_CASE_MS)
    expect(warn).toHaveBeenCalled()
  })

  it('falls back when the override is not a number, and says so', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.stubEnv('VITE_REQUEST_TIMEOUT_MS', 'two minutes')
    const config = await reload()

    expect(config.REQUEST_TIMEOUT_MS).toBeGreaterThan(BACKEND_WORST_CASE_MS)
    expect(warn).toHaveBeenCalled()
  })

  it('ignores an empty override without complaining', async () => {
    // Vercel hands an unset variable through as an empty string, which is not
    // a mistake and should not print a warning on every page load.
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.stubEnv('VITE_REQUEST_TIMEOUT_MS', '')
    const config = await reload()

    expect(config.REQUEST_TIMEOUT_MS).toBe(REQUEST_TIMEOUT_MS)
    expect(warn).not.toHaveBeenCalled()
  })
})
