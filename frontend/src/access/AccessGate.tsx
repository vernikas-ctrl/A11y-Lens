/**
 * The front door. Task 8.0.
 *
 * The app is link-only, so this is not a step in the middle of a flow -- it
 * is the shell. Until the backend has confirmed a code, nothing else renders
 * at all, and `children` is not even constructed.
 *
 * Five states, because a gate that only knows "in" and "out" shows the wrong
 * thing in the three that matter most:
 *
 *   checking   a stored code is being confirmed with the backend
 *   locked     no code, or the one offered was refused
 *   open       confirmed
 *   waking     the backend did not answer; it is probably asleep, and we are
 *              waiting for it with a timer rather than with a person's patience
 *   offline    it has had long enough and is not coming back
 *
 * `offline` is separate from `locked` on purpose. Telling somebody their code
 * is wrong when the truth is that a free-tier backend is still waking up
 * sends them hunting for a typo that is not there.
 *
 * `waking` is separate from `offline` for the same reason one step further on,
 * and it is task 8.10. A free host stops the service after about fifteen
 * minutes of quiet and takes roughly half a minute to start it again, so the
 * single most likely visitor -- the first one after a quiet spell -- met a
 * flat "Could not reach A11y-Lens". That describes a symptom and blames
 * nothing. This waits for the server, says so, and gives up honestly when it
 * has waited long enough.
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
import { checkHealth, verifyCode } from '../api/client'
import { ACCESS_CODE } from '../config'
import { forgetCode, readStoredCode, storeCode } from './storage'

type Status = 'checking' | 'locked' | 'open' | 'waking' | 'offline'

/**
 * How long to keep waiting, and how long between tries.
 *
 * Adds up to 48 seconds of waiting across five attempts, which covers the
 * half-minute a cold start usually needs with room to spare. The gaps widen
 * because the longer a server has failed to appear, the less likely the next
 * second is the one.
 */
const RETRY_DELAYS_MS = [3_000, 5_000, 8_000, 12_000, 20_000]

/**
 * **The retries poll `/health`, never `/verify`.**
 *
 * `/verify` is rate limited to five requests a minute, shared with every
 * other endpoint, and five retries is exactly that budget. A gate that
 * retried the real call would spend the whole allowance waking the server up
 * and then be refused for rate limiting the moment it succeeded -- causing
 * the error it exists to avoid. `/health` is deliberately exempt from the
 * limiter and does no work, which makes it the right question to ask
 * repeatedly: not "is my code valid" but "are you there yet".
 */
function looksAsleep(error: { code: string; status: number | null }): boolean {
  if (error.code === 'network_error' || error.code === 'request_timeout') return true
  // A host that has stopped the service answers on its behalf while starting
  // it, with a gateway error of its own. Only /verify reaches this function,
  // so there is no confusion with the scanner's own 502 and 504.
  return error.status === 502 || error.status === 503 || error.status === 504
}

const NOT_RESPONDING =
  'A11y-Lens is still not answering. It may be down rather than asleep — ' +
  'worth telling whoever sent you the link.'

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
  // The code the waking loop is waiting to retry. A ref rather than state
  // because changing it must not restart the loop that reads it.
  const wakingFor = useRef<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  /**
   * Asks the backend, sets the state every caller wants, and reports which
   * way it went. The return value exists for the waking loop below: it needs
   * to know whether to carry on waiting, and reading that back out of state
   * inside an async loop is how stale-closure bugs happen.
   */
  const check = useCallback(async (
    code: string,
    signal?: AbortSignal,
  ): Promise<'open' | 'refused' | 'asleep'> => {
    const result = await verifyCode(code, { signal })

    if (result.ok) {
      storeCode(code)
      setStatus('open')
      setProblem(null)
      return 'open'
    }

    if (result.error.code === 'unauthorized') {
      // Only now is the stored code known to be wrong. Clearing it on any
      // failure would log somebody out because their wifi dropped.
      forgetCode()
      setStatus('locked')
      setProblem('That code is not right. Check it and try again.')
      return 'refused'
    }

    if (result.error.code === 'rate_limited') {
      const wait = result.error.retryAfterSeconds
      setStatus('locked')
      setProblem(
        wait === undefined
          ? 'Too many attempts. Wait a moment and try again.'
          : `Too many attempts. Wait ${wait} seconds and try again.`,
      )
      return 'refused'
    }

    // Everything else -- the backend asleep, a timeout, a network failure.
    // The code may well be fine, so it is kept rather than thrown away.
    //
    // **This must stay below the `unauthorized` branch.** A refusal answered
    // with "waiting for the server" would turn the gate into a waiting room
    // that eventually lets anybody in. The order is what prevents it, not
    // anything inside `looksAsleep`; five tests fail if the two are swapped.
    if (looksAsleep(result.error)) {
      wakingFor.current = code
      setStatus('waking')
      setProblem(null)
      return 'asleep'
    }

    setStatus('offline')
    setProblem(result.error.message)
    return 'refused'
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

  // Task 8.10. While the backend looks asleep, wait for it on a timer rather
  // than on somebody's patience: poll /health until it answers, then retry
  // the code once, and give up honestly when the attempts run out.
  //
  // The loop lives in an effect because it is synchronising with something
  // outside React -- a server that is starting up on its own schedule -- and
  // because it has to be torn down cleanly when the component goes away.
  useEffect(() => {
    if (status !== 'waking') return
    const code = wakingFor.current
    if (code === null) return

    const controller = new AbortController()
    let stopped = false

    async function waitForTheServer() {
      for (let index = 0; index < RETRY_DELAYS_MS.length; index += 1) {
        await new Promise((resolve) => setTimeout(resolve, RETRY_DELAYS_MS[index]))
        if (stopped) return

        setAttempt(index + 1)
        const health = await checkHealth({ signal: controller.signal })
        if (stopped) return
        if (!health.ok) continue

        // It is answering. Spend one of the five rate-limited requests now,
        // and let `check` decide what the state becomes.
        const outcome = await check(code as string, controller.signal)
        if (stopped) return
        // 'asleep' means it answered /health and then went away again, which
        // is possible mid-start. Keep waiting rather than declaring victory.
        if (outcome !== 'asleep') return
      }

      if (!stopped) {
        setStatus('offline')
        setProblem(NOT_RESPONDING)
      }
    }

    void waitForTheServer().catch(() => {
      // The only rejection is the abort below, on unmount.
    })

    return () => {
      stopped = true
      controller.abort()
    }
    // `status` is the trigger and `check` is stable. `attempt` is written by
    // this loop and must not be read by it, or every tick would restart it.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [status, check])

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

  // Task 8.10's screen. Deliberately not an error: nothing has gone wrong
  // yet, and dressing a cold start in red teaches people to distrust a
  // working app. It says what is happening, roughly how long, and offers a
  // button for somebody who would rather not wait for the next tick.
  if (status === 'waking') {
    const total = RETRY_DELAYS_MS.length
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 px-6 py-16">
        <div>
          <h1 className="text-2xl font-semibold text-ink">A11y-Lens</h1>
          {/* polite, not assertive: this is reassurance, and interrupting a
              screen reader to deliver reassurance is not reassuring. */}
          <p role="status" aria-live="polite" className="mt-3 text-ink">
            Waking the server up. This usually takes about 30 seconds.
          </p>
          <p className="mt-2 text-sm text-muted">
            A11y-Lens runs on a free host that stops the service when nobody has
            used it for a while. Nothing is wrong, and your code has not been
            rejected — there is just nothing there to answer yet.
          </p>
        </div>

        {/* An honest count rather than a bar that fills at a made-up rate.
            It also quietly tells somebody the waiting is finite. */}
        <p className="text-sm text-muted">
          {attempt === 0
            ? `Waiting… (up to ${total} tries)`
            : `Try ${attempt} of ${total}…`}
        </p>

        <button
          type="button"
          onClick={() => {
            const code = wakingFor.current
            if (code === null) return
            void check(code)
          }}
          className="self-start rounded-md border border-muted px-4 py-2 text-sm font-medium text-ink"
        >
          Try now
        </button>
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
