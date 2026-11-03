/**
 * Where the access code lives between page loads. Task 8.0.
 *
 * **sessionStorage, not localStorage.** The difference is how long it lasts:
 * sessionStorage is emptied when the tab is closed, localStorage survives
 * until something deletes it. That means the code has to be typed again on
 * each visit, which is friction for the handful of people who have the link
 * -- and the reason to accept it is the borrowed or shared computer, where a
 * remembered code is a code left behind for whoever sits down next. Closing
 * the tab is something people already do without being told.
 *
 * Every access is wrapped, because storage is not guaranteed to work. Safari
 * in private browsing, a browser configured to block site data, and an iframe
 * with third-party storage disabled all **throw** rather than returning
 * nothing. An unhandled throw here would blank the whole app at startup, so
 * failing to remember the code is treated as not having one -- the person
 * types it again, which is exactly what they would do anyway.
 */

const KEY = 'a11y-lens.access-code'

export function readStoredCode(): string | null {
  try {
    const stored = window.sessionStorage.getItem(KEY)
    return stored && stored.length > 0 ? stored : null
  } catch {
    return null
  }
}

export function storeCode(code: string): void {
  try {
    window.sessionStorage.setItem(KEY, code)
  } catch {
    // Nothing to do and nothing worth telling the person: the app works, it
    // will just ask again next time.
  }
}

export function forgetCode(): void {
  try {
    window.sessionStorage.removeItem(KEY)
  } catch {
    // Already effectively forgotten if storage is unavailable.
  }
}
