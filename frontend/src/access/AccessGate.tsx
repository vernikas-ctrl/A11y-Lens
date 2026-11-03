/**
 * The front door. Task 8.0.
 *
 * The app is link-only, so this is not a step in the middle of a flow -- it
 * is the shell. Until the backend has confirmed a code, nothing else renders
 * at all, and `children` is not even constructed.
 *
 * Four states, because a gate that only knows "in" and "out" shows the wrong
 * thing in the two that matter most:
 *
 *   checking   a stored code is being confirmed with the backend
 *   locked     no code, or the one offered was refused
 *   open       confirmed
 *   offline    the backend could not be reached, so we do not know
 *
 * `offline` is separate from `locked` on purpose. Telling somebody their code
 * is wrong when the truth is that a free-tier backend is still waking up
 * sends them hunting for a typo that is not there.
 *
 * Accessibility is built in here rather than audited in later, because this
 * is the first screen Phase 9 looks at and the one nobody can skip:
 *
 *   - the input has a real <label>, not a placeholder standing in for one
 *   - errors are tied to the input with aria-describedby, so a screen reader
 *     reads the reason when the field takes focus
 *   - the error is also a live region, so it is announced when it appears
 *     rather than only when the field is visited
 *   - the submit button says what is happening and is disabled while busy
 *   - focus moves to the field when a code is refused, so the next keystroke
 *     goes somewhere useful
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { verifyCode } from '../api/client'
import { ACCESS_CODE } from '../config'
import { forgetCode, readStoredCode, storeCode } from './storage'

type Status = 'checking' | 'locked' | 'open' | 'offline'

interface Props {
  children: ReactNode
}

export default function AccessGate({ children }: Props) {
  // Read once, during the first render rather than in an effect afterwards.
  // Doing it in an effect meant setting state synchronously inside one, which
  // starts a second render before the browser has painted the first -- and the
  // linter is right that it is avoidable: whether there is a code to check is
  // knowable immediately, so the starting state can simply be correct.
  const [initialCode] = useState<string | null>(() => readStoredCode() ?? (ACCESS_CODE || null))
  const [status, setStatus] = useState<Status>(initialCode === null ? 'locked' : 'checking')
  const [typed, setTyped] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  /**
   * Asks the backend. Returns nothing and sets state, because every caller
   * wants the same four outcomes handled the same way.
   */
  const check = useCallback(async (code: string, signal?: AbortSignal) => {
    const result = await verifyCode(code, { signal })

    if (result.ok) {
      storeCode(code)
      setStatus('open')
      setProblem(null)
      return
    }

    if (result.error.code === 'unauthorized') {
      // Only now is the stored code known to be wrong. Clearing it on any
      // failure would log somebody out because their wifi dropped.
      forgetCode()
      setStatus('locked')
      setProblem('That code is not right. Check it and try again.')
      return
    }

    if (result.error.code === 'rate_limited') {
      const wait = result.error.retryAfterSeconds
      setStatus('locked')
      setProblem(
        wait === undefined
          ? 'Too many attempts. Wait a moment and try again.'
          : `Too many attempts. Wait ${wait} seconds and try again.`,
      )
      return
    }

    // Everything else -- the backend asleep, a timeout, a network failure.
    // The code may well be fine, so it is kept rather than thrown away.
    setStatus('offline')
    setProblem(result.error.message)
  }, [])

  // On load: if a code was configured at build time or remembered from
  // earlier in this tab's session, confirm it before showing anything. A
  // stored code that the backend no longer accepts must not open the app,
  // and must not open it even for a moment -- `status` starts at 'checking',
  // so the app is not rendered while this is in flight.
  useEffect(() => {
    if (initialCode === null) return

    const controller = new AbortController()
    // `check` does set state, but only after awaiting a network round-trip,
    // which is not the cascading re-render the rule is looking for. Asking
    // the backend whether a code is still valid is synchronising with an
    // external system, which is exactly what an effect is for.
    // oxlint-disable-next-line react/set-state-in-effect
    void check(initialCode, controller.signal).catch(() => {
      // The only way `check` rejects is the abort below, which happens when
      // this component goes away. Nothing left to tell.
    })
    return () => controller.abort()
  }, [check, initialCode])

  // When a code is refused, put the cursor back in the field. Without this
  // the next keystroke goes nowhere and a keyboard user has to find their way
  // back to the input by hand.
  useEffect(() => {
    if (status === 'locked' && problem !== null) inputRef.current?.focus()
  }, [status, problem])

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const code = typed.trim()
    if (code === '') {
      setProblem('Enter the code you were given.')
      inputRef.current?.focus()
      return
    }

    setSubmitting(true)
    setProblem(null)
    await check(code)
    setSubmitting(false)
  }

  if (status === 'open') return <>{children}</>

  // Deliberately plain while the stored code is being confirmed: a flash of
  // the code form followed by the app is worse than a moment of nothing, and
  // this normally lasts a few milliseconds.
  if (status === 'checking') {
    return (
      <main className="mx-auto flex min-h-screen max-w-md items-center justify-center px-6">
        <p className="text-muted" role="status">
          Checking your access code&hellip;
        </p>
      </main>
    )
  }

  const offline = status === 'offline'

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 px-6 py-16">
      <div>
        <h1 className="text-2xl font-semibold text-ink">A11y-Lens</h1>
        <p className="mt-2 text-muted">
          This tool is shared by link. Enter the code you were given to continue.
        </p>
      </div>

      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-3">
        <label htmlFor="access-code" className="font-medium text-ink">
          Access code
        </label>

        <input
          ref={inputRef}
          id="access-code"
          name="access-code"
          type="password"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          // Not `current-password`: this is a shared code, and offering to
          // save it to a password manager alongside real passwords overstates
          // what it is.
          autoComplete="off"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          // Points at the message below, so a screen reader reads the reason
          // when the field takes focus and not only when it first appeared.
          aria-describedby={problem ? 'access-code-problem' : undefined}
          aria-invalid={problem !== null && !offline}
          disabled={submitting}
          className="rounded-md border border-muted bg-paper px-3 py-2 text-ink disabled:opacity-60"
        />

        {/* Always in the document, even when empty. A live region added to
            the page at the same moment as its text is often not announced;
            one that is already there and then fills reliably is. */}
        <p
          id="access-code-problem"
          role={offline ? 'status' : 'alert'}
          aria-live={offline ? 'polite' : 'assertive'}
          className={`min-h-6 text-sm ${offline ? 'text-muted' : 'text-alert'}`}
        >
          {problem}
        </p>

        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-primary px-4 py-2 font-medium text-paper disabled:opacity-60"
        >
          {submitting ? 'Checking…' : offline ? 'Try again' : 'Continue'}
        </button>
      </form>

      <p className="text-sm text-muted">
        Don&rsquo;t have a code? Ask whoever sent you the link.
      </p>
    </main>
  )
}
