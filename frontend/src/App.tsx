/**
 * What sits behind the access gate.
 *
 * The saved demo report is what the panel starts with, so the first thing
 * somebody sees is the tool working rather than an empty form. Their first
 * scan replaces it.
 */

import { demoReport, EXPLANATIONS_ARE_HAND_WRITTEN } from './demo/demoReport'
import ScanPanel from './scan/ScanPanel'

export default function App() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 px-6 py-12">
      <header>
        <h1 className="text-3xl font-semibold text-ink">A11y-Lens</h1>
        <p className="mt-2 text-muted">
          Scans a web page for accessibility problems and explains them in plain language.
        </p>
      </header>

      <ScanPanel
        initialReport={demoReport}
        initialReportIsHandWritten={EXPLANATIONS_ARE_HAND_WRITTEN}
      />

      <footer className="border-t border-surface pt-4 text-sm text-muted">
        <p>
          Automated tools find roughly a third of accessibility problems. A clean report is a
          good sign, not a guarantee.
        </p>
      </footer>
    </main>
  )
}
