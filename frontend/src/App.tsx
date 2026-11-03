/**
 * A placeholder, on purpose.
 *
 * Phase 7 is the skeleton: the toolchain, the palette, the test runner and
 * the API client. The first real screen is task 8.0, the access code gate,
 * and building any of it here would mean building it outside the shell it has
 * to live inside.
 *
 * What this page does do is prove the parts are connected -- Tailwind's
 * palette renders, React mounts, the build type-checks -- which is the only
 * claim Phase 7 makes.
 */
export default function App() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 px-6 py-16">
      <div>
        <h1 className="text-3xl font-semibold text-ink">A11y-Lens</h1>
        <p className="mt-2 text-muted">
          Scans a web page for accessibility problems and explains them in plain language.
        </p>
      </div>

      <p className="rounded-md border border-surface bg-surface p-4 text-ink">
        The frontend skeleton is in place. The app itself starts at task 8.0, the
        access code screen.
      </p>

      <p className="text-sm text-muted">
        Phase 7 of 11 &middot;{' '}
        <a className="text-primary underline" href="https://github.com/vernikas-ctrl/A11y-Lens">
          github.com/vernikas-ctrl/A11y-Lens
        </a>
      </p>
    </main>
  )
}
