/**
 * What sits behind the access gate.
 *
 * Right now: the saved demo report (task 8.1). The URL input, the loading
 * state and the live result come in the next chunk -- 8.2, 8.4, 8.8 and 8.9 --
 * and this becomes the screen the result renders into.
 *
 * The demo renders with no backend call at all, which is the whole reason it
 * is built before the live flow: the backend is going on a free host that
 * sleeps, and the first thing somebody sees after typing the access code
 * should be the tool working, not a cold start.
 */

import { demoReport, DEMO_SUBJECT, EXPLANATIONS_ARE_HAND_WRITTEN } from './demo/demoReport'
import ReportView from './report/ReportView'

export default function App() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 px-6 py-12">
      <header>
        <h1 className="text-3xl font-semibold text-ink">A11y-Lens</h1>
        <p className="mt-2 text-muted">
          Scans a web page for accessibility problems and explains them in plain language.
        </p>
      </header>

      <div className="rounded-md border border-surface bg-surface p-4">
        <h2 className="font-medium text-ink">Example scan</h2>
        <p className="mt-1 text-sm text-muted">
          This is a saved report from {DEMO_SUBJECT}. Scanning a page of your own comes next.
        </p>
      </div>

      <ReportView
        report={demoReport}
        explanationsAreHandWritten={EXPLANATIONS_ARE_HAND_WRITTEN}
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
