/**
 * The access gate. Task 8.0.
 *
 * Two things are being checked here, and the second is the one that is easy
 * to forget: that the gate is correct, and that it is usable without a mouse
 * or a screen. The accessibility assertions are not extra credit -- this is
 * the screen Phase 9 audits first and the one nobody can skip.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AccessGate from './AccessGate'
import { readStoredCode, storeCode } from './storage'

/** Stands in for the protected app. */
function Protected() {
  return <p>the real application</p>
}

function renderGate() {
  return render(
    <AccessGate>
      <Protected />
    </AccessGate>,
  )
}

/** A `fetch` stub answering /verify however the test needs. */
function verifyAnswers(init: { status: number; body?: unknown; headers?: Record<string, string> }) {
  // Typed with fetch's own parameters so `mock.calls` carries them; an
  // argument-less stub gives an empty tuple and reading calls[0][1] will not
  // compile.
  return vi.fn(async (_url: string, _init: RequestInit) =>
    new Response(JSON.stringify(init.body ?? { ok: true }), {
      status: init.status,
      headers: { 'Content-Type': 'application/json', ...init.headers },
    }),
  )
}

/** The X-Access-Code the stub was called with, for assertions. */
function sentCode(stub: ReturnType<typeof verifyAnswers>): string | undefined {
  const headers = stub.mock.calls[0]?.[1]?.headers as Record<string, string> | undefined
  return headers?.['X-Access-Code']
}

const UNAUTHORIZED = {
  status: 401,
  body: { error: { code: 'unauthorized', message: 'That access code is not right.', detail: null } },
}

beforeEach(() => {
  window.sessionStorage.clear()
  vi.stubGlobal('fetch', verifyAnswers({ status: 200 }))
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.sessionStorage.clear()
})

describe('with no code yet', () => {
  it('shows the code form and not the app', async () => {
    vi.stubGlobal('fetch', verifyAnswers(UNAUTHORIZED))
    renderGate()

    expect(await screen.findByLabelText('Access code')).toBeVisible()
    expect(screen.queryByText('the real application')).not.toBeInTheDocument()
  })

  it('does not render the protected app anywhere in the document', async () => {
    // Not merely hidden with CSS -- hidden content is still reachable by a
    // screen reader and still in the page source. The app is link-only, so
    // "nothing renders without a code" has to mean nothing.
    vi.stubGlobal('fetch', verifyAnswers(UNAUTHORIZED))
    const { container } = renderGate()

    await screen.findByLabelText('Access code')
    expect(container.textContent).not.toContain('the real application')
  })
})

describe('entering a code', () => {
  it('opens the app when the backend accepts it', async () => {
    vi.stubGlobal('fetch', verifyAnswers(UNAUTHORIZED))
    const user = userEvent.setup()
    renderGate()

    const field = await screen.findByLabelText('Access code')
    vi.stubGlobal('fetch', verifyAnswers({ status: 200 }))
    await user.type(field, 'the-right-code')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByText('the real application')).toBeVisible()
  })

  it('explains a wrong code without saying how it was wrong', async () => {
    vi.stubGlobal('fetch', verifyAnswers(UNAUTHORIZED))
    const user = userEvent.setup()
    renderGate()

    const field = await screen.findByLabelText('Access code')
    await user.type(field, 'wrong')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    const problem = await screen.findByRole('alert')
    expect(problem).toHaveTextContent(/not right/i)
    expect(screen.queryByText('the real application')).not.toBeInTheDocument()
  })

  it('refuses an empty code without troubling the backend', async () => {
    vi.stubGlobal('fetch', verifyAnswers(UNAUTHORIZED))
    const user = userEvent.setup()
    renderGate()

    await screen.findByLabelText('Access code')
    const callsBefore = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.length
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/enter the code/i)
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(callsBefore)
  })

  it('trims surrounding spaces, which a copied code usually has', async () => {
    vi.stubGlobal('fetch', verifyAnswers(UNAUTHORIZED))
    const user = userEvent.setup()
    renderGate()

    const field = await screen.findByLabelText('Access code')
    const accepting = verifyAnswers({ status: 200 })
    vi.stubGlobal('fetch', accepting)
    await user.type(field, '  spaced-code  ')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await screen.findByText('the real application')
    expect(sentCode(accepting)).toBe('spaced-code')
  })

  it('says the backend is unreachable rather than blaming the code', async () => {
    // The difference that matters: a wrong code is the person's problem and
    // a sleeping backend is not. Telling them their code is wrong sends them
    // hunting for a typo that is not there.
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const user = userEvent.setup()
    renderGate()

    const field = await screen.findByLabelText('Access code')
    await user.type(field, 'probably-fine')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    const message = await screen.findByRole('status')
    expect(message).toHaveTextContent(/could not reach/i)
    expect(message).not.toHaveTextContent(/not right/i)
    // And it offers another go rather than looking like a dead end.
    expect(screen.getByRole('button', { name: 'Try again' })).toBeVisible()
  })

  it('passes a rate limit through with the wait', async () => {
    vi.stubGlobal(
      'fetch',
      verifyAnswers({
        status: 429,
        body: { error: { code: 'rate_limited', message: 'Too many.', detail: null } },
        headers: { 'Retry-After': '30' },
      }),
    )
    const user = userEvent.setup()
    renderGate()

    const field = await screen.findByLabelText('Access code')
    await user.type(field, 'guessing')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('30 seconds')
  })
})

describe('remembering the code', () => {
  it('survives a reload within the same tab', async () => {
    storeCode('remembered-code')
    const accepting = verifyAnswers({ status: 200 })
    vi.stubGlobal('fetch', accepting)

    renderGate()

    expect(await screen.findByText('the real application')).toBeVisible()
    expect(sentCode(accepting)).toBe('remembered-code')
  })

  it('confirms a remembered code with the backend instead of trusting it', async () => {
    // Anybody can write anything into sessionStorage from the console. If the
    // gate trusted what it finds there, it would not be a gate.
    storeCode('revoked-code')
    vi.stubGlobal('fetch', verifyAnswers(UNAUTHORIZED))

    renderGate()

    expect(await screen.findByLabelText('Access code')).toBeVisible()
    expect(screen.queryByText('the real application')).not.toBeInTheDocument()
  })

  it('forgets a code the backend has rejected', async () => {
    storeCode('revoked-code')
    vi.stubGlobal('fetch', verifyAnswers(UNAUTHORIZED))

    renderGate()

    await screen.findByLabelText('Access code')
    await waitFor(() => expect(readStoredCode()).toBeNull())
  })

  it('keeps the code when the backend is merely unreachable', async () => {
    // Being logged out because the wifi dropped would be its own small
    // injustice, and the code is probably correct.
    storeCode('probably-fine')
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))

    renderGate()

    await screen.findByRole('status')
    expect(readStoredCode()).toBe('probably-fine')
  })

  it('works when storage throws, as it does in private browsing', async () => {
    // Safari in private mode and a browser with site data blocked both throw
    // rather than returning nothing. An unhandled throw here would blank the
    // whole app at startup.
    const boom = () => { throw new DOMException('denied', 'SecurityError') }
    vi.spyOn(window.sessionStorage, 'getItem').mockImplementation(boom)
    vi.spyOn(window.sessionStorage, 'setItem').mockImplementation(boom)
    vi.stubGlobal('fetch', verifyAnswers({ status: 200 }))
    const user = userEvent.setup()

    renderGate()

    const field = await screen.findByLabelText('Access code')
    await user.type(field, 'a-code')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByText('the real application')).toBeVisible()
    vi.restoreAllMocks()
  })
})

describe('reachable without a mouse or a screen', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', verifyAnswers(UNAUTHORIZED))
  })

  it('labels the input with a real label element', async () => {
    // A placeholder is not a label: it disappears as soon as there is text,
    // and several screen readers do not announce it at all.
    renderGate()

    const field = await screen.findByLabelText('Access code')
    expect(field.tagName).toBe('INPUT')
    expect(field).toHaveAccessibleName('Access code')
  })

  it('ties the error to the field so it is read on focus', async () => {
    const user = userEvent.setup()
    renderGate()

    const field = await screen.findByLabelText('Access code')
    await user.type(field, 'wrong')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await screen.findByRole('alert')
    expect(await screen.findByLabelText('Access code')).toHaveAccessibleDescription(/not right/i)
  })

  it('marks the field invalid so it is announced as such', async () => {
    const user = userEvent.setup()
    renderGate()

    const field = await screen.findByLabelText('Access code')
    await user.type(field, 'wrong')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await screen.findByRole('alert')
    expect(await screen.findByLabelText('Access code')).toHaveAttribute('aria-invalid', 'true')
  })

  it('puts the cursor back in the field after a refusal', async () => {
    // Otherwise the next keystroke goes nowhere and a keyboard user has to
    // find their way back to the input by hand.
    const user = userEvent.setup()
    renderGate()

    const field = await screen.findByLabelText('Access code')
    await user.type(field, 'wrong')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await screen.findByRole('alert')
    await waitFor(() => expect(screen.getByLabelText('Access code')).toHaveFocus())
  })

  it('can be completed with the keyboard alone', async () => {
    const user = userEvent.setup()
    renderGate()

    await screen.findByLabelText('Access code')
    await user.tab()
    expect(screen.getByLabelText('Access code')).toHaveFocus()

    vi.stubGlobal('fetch', verifyAnswers({ status: 200 }))
    await user.keyboard('a-code{Enter}')

    expect(await screen.findByText('the real application')).toBeVisible()
  })

  it('has exactly one level-one heading', async () => {
    renderGate()

    await screen.findByLabelText('Access code')
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })

  it('says what to do when you have no code at all', async () => {
    // A dead end with no way forward is its own accessibility problem.
    renderGate()

    expect(await screen.findByText(/ask whoever sent you the link/i)).toBeVisible()
  })

  it('disables the button while checking so it cannot be submitted twice', async () => {
    let release: (value: Response) => void = () => {}
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { release = resolve })))
    const user = userEvent.setup()
    renderGate()

    // The first render settles into the locked state before this runs.
    const field = await screen.findByLabelText('Access code')
    await user.type(field, 'a-code')
    await user.click(screen.getByRole('button'))

    await waitFor(() => expect(screen.getByRole('button')).toBeDisabled())
    expect(screen.getByRole('button')).toHaveTextContent(/checking/i)

    release(new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    expect(await screen.findByText('the real application')).toBeVisible()
  })
})

describe('the moment before the answer comes back', () => {
  it('shows nothing of the app while a stored code is still being checked', async () => {
    // Found by a mutation: setting the gate open immediately and letting the
    // check close it again afterwards passed all 21 tests, because every one
    // of them waits for the settled state. In a browser that is a flash of
    // the real app for anybody whose stored code is no longer valid -- and on
    // a slow connection, not a flash at all.
    storeCode('slow-to-confirm')
    let release: (value: Response) => void = () => {}
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { release = resolve })))

    renderGate()

    // While the request is in flight: the holding message, and no app.
    expect(await screen.findByRole('status')).toHaveTextContent(/checking your access code/i)
    expect(screen.queryByText('the real application')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Access code')).not.toBeInTheDocument()

    release(new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))

    expect(await screen.findByText('the real application')).toBeVisible()
  })

  it('shows nothing of the app while a typed code is being checked', async () => {
    vi.stubGlobal('fetch', verifyAnswers(UNAUTHORIZED))
    const user = userEvent.setup()
    renderGate()

    const field = await screen.findByLabelText('Access code')
    let release: (value: Response) => void = () => {}
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { release = resolve })))
    await user.type(field, 'a-code')
    await user.click(screen.getByRole('button'))

    await waitFor(() => expect(screen.getByRole('button')).toBeDisabled())
    expect(screen.queryByText('the real application')).not.toBeInTheDocument()

    release(new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    expect(await screen.findByText('the real application')).toBeVisible()
  })
})
