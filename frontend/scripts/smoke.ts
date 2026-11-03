/**
 * Task 7.4's "done when", against a real backend.
 *
 *     cd frontend
 *     npx vite-node scripts/smoke.ts
 *
 * Deliberately **not** part of `npm test`. The test suite stubs `fetch` and
 * must keep passing with nothing running; this needs the backend up, so
 * putting it in the suite would mean the suite fails on a laptop where it
 * isn't -- which teaches people to ignore failures.
 *
 * Reads the same `.env` the app does, so what it exercises is the real
 * configuration rather than values typed in here. It never prints the access
 * code.
 *
 * Before running it, in another terminal:
 *
 *     cd backend
 *     .venv/Scripts/python -m uvicorn app.main:app --port 8000
 */

import { ACCESS_CODE, API_BASE_URL } from '../src/config'
import { checkHealth, scanUrl, verifyCode } from '../src/api/client'

const PAGE_TO_SCAN = 'https://example.com'

function line(label: string, value: string) {
  console.log(`  ${label.padEnd(26)} ${value}`)
}

async function main(): Promise<number> {
  console.log(`\nbackend:     ${API_BASE_URL}`)
  console.log(`access code: ${ACCESS_CODE ? 'configured' : 'NOT SET -- check frontend/.env'}\n`)

  let failures = 0
  const fail = (why: string) => {
    console.log(`  FAILED: ${why}`)
    failures += 1
  }

  console.log('health')
  const health = await checkHealth()
  if (health.ok) {
    line('status', health.data.status)
    line('version', health.data.version)
  } else {
    fail(`${health.error.code}: ${health.error.message}`)
    console.log('\n  Is the backend running on that address?\n')
    return 1
  }

  console.log('\nverify, with a wrong code')
  const wrong = await verifyCode('definitely-not-the-code')
  if (wrong.ok) fail('a wrong code was accepted')
  else if (wrong.error.code !== 'unauthorized') fail(`expected unauthorized, got ${wrong.error.code}`)
  else line('refused with', `${wrong.error.status} ${wrong.error.code}`)

  console.log('\nverify, with the configured code')
  const right = await verifyCode(ACCESS_CODE)
  if (!right.ok) fail(`${right.error.code}: ${right.error.message}`)
  else line('accepted', JSON.stringify(right.data))

  console.log(`\nscan ${PAGE_TO_SCAN}`)
  const started = Date.now()
  const scan = await scanUrl(PAGE_TO_SCAN)
  if (!scan.ok) {
    fail(`${scan.error.code}: ${scan.error.message}`)
  } else {
    const report = scan.data
    line('url after redirects', report.url)
    line('page title', report.page_title ?? '(none)')
    line('issues found', String(report.issues.length))
    line('summary total', String(report.summary.total))
    line('explanations available', String(report.explanations_available))
    if (report.explanations_unavailable_reason) {
      line('reason', report.explanations_unavailable_reason)
    }
    line('backend took', `${report.scan_duration_ms}ms`)
    line('round trip', `${Date.now() - started}ms`)

    // The point of the typed client: these are read as properties, not dug
    // out of an `any`. A missing or renamed field is a compile error.
    const first = report.issues[0]
    if (first) {
      console.log('\n  first issue, read through the types:')
      line('  rule_id', first.rule_id)
      line('  severity', first.severity)
      line('  wcag', first.wcag.join(', ') || '(none)')
      line('  explanation', first.explanation ? first.explanation.what : 'null (as expected)')
    }

    // Contract rule 4, checked rather than assumed.
    const broken = report.issues.filter(
      (issue) => (issue.explanation === null) !== (issue.fix === null),
    )
    if (broken.length > 0) fail(`${broken.length} issue(s) have explanation and fix out of step`)
  }

  console.log(`\nscan a blocked address (SSRF guard)`)
  const blocked = await scanUrl('http://127.0.0.1:8000')
  if (blocked.ok) fail('a loopback address was scanned')
  else if (blocked.error.code !== 'blocked_address') fail(`expected blocked_address, got ${blocked.error.code}`)
  else line('refused with', `${blocked.error.status} ${blocked.error.code}`)

  console.log(failures === 0 ? '\nall checks passed\n' : `\n${failures} check(s) failed\n`)
  return failures === 0 ? 0 : 1
}

main().then((code) => process.exit(code))
