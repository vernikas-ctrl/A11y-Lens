/**
 * What the frontend checks about a URL before sending it. Task 8.2.
 *
 * **Deliberately much weaker than the backend's check.** `app/url_safety.py`
 * resolves DNS and refuses private, loopback, link-local and reserved
 * addresses, and it is the only thing that decides whether a scan happens.
 * This catches the handful of mistakes that are obvious without a network
 * round trip -- an empty box, a sentence instead of an address, a `file://`
 * path -- so somebody who mistypes gets told in a few milliseconds instead of
 * a few seconds.
 *
 * Nothing here is a security measure. Anything this misses the backend
 * refuses, and duplicating the SSRF rules in a file the browser downloads
 * would mean two sets of rules drifting apart, with the weaker one looking
 * authoritative.
 */

const MAX_URL_LENGTH = 2_000

/** Null when the URL looks sendable, otherwise what to tell the person. */
export function problemWith(raw: string): string | null {
  const url = raw.trim()

  if (url === '') return 'Enter the address of a page to scan.'

  if (url.length > MAX_URL_LENGTH) {
    return `That address is too long. The limit is ${MAX_URL_LENGTH} characters.`
  }

  // Typing "example.com" is the normal thing to do, and `prepare` below adds
  // the https:// for them. What cannot be rescued is a scheme that is
  // explicitly something else.
  const scheme = url.match(/^([a-z][a-z0-9+.-]*):/i)?.[1]?.toLowerCase()
  if (scheme !== undefined && scheme !== 'http' && scheme !== 'https') {
    return `A11y-Lens can only scan web pages, so the address needs to start with https:// — not ${scheme}://`
  }

  let parsed: URL
  try {
    parsed = new URL(prepare(url))
  } catch {
    return 'That does not look like a web address. It should look like https://example.com'
  }

  if (parsed.hostname === '') {
    return 'That address has no site name in it. It should look like https://example.com'
  }

  // A hostname with no dot and no port is almost always a typo or an internal
  // name. The backend refuses internal names anyway, after resolving them;
  // saying so here saves the round trip and is a clearer message than
  // "blocked address".
  if (!parsed.hostname.includes('.') && parsed.hostname !== 'localhost') {
    return 'That address is missing its ending, like .com or .org.'
  }

  return null
}

/**
 * What actually gets sent.
 *
 * Adds `https://` when no scheme was typed, because `example.com` is what
 * people type and rejecting it would be pedantry. https rather than http:
 * if the site only serves http it will redirect, and guessing the secure one
 * first is the right default.
 */
export function prepare(raw: string): string {
  const url = raw.trim()
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(url) ? url : `https://${url}`
}
