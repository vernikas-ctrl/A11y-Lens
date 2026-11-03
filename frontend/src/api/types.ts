/**
 * The shapes `docs/api-contract.md` describes, as TypeScript.
 *
 * **Written by hand from the contract, not generated from the backend.** The
 * contract is the agreement between the two halves; generating these from the
 * backend's code would mean a backend mistake silently becomes the frontend's
 * definition of correct, and the disagreement the contract exists to catch
 * would never surface. Two independent readings of one document catch what
 * one reading cannot.
 *
 * Section numbers below point at the contract. If this file and that file
 * disagree, this file is wrong.
 */

/** Contract 2.2: axe-core's own scale, not a custom one. */
export type Severity = 'critical' | 'serious' | 'moderate' | 'minor'

/** Contract 2.3: only ever present when explanations are unavailable. */
export type UnavailableReason = 'daily_limit_reached' | 'api_unavailable'

/** Contract 3: the frontend branches on these, never on `message`. */
export type ErrorCode =
  | 'invalid_url'
  | 'blocked_address'
  | 'unauthorized'
  | 'not_found'
  | 'method_not_allowed'
  | 'rate_limited'
  | 'daily_limit_reached'
  | 'unreachable'
  | 'scan_timeout'
  | 'internal_error'

/**
 * Contract 2.2: two fields of plain prose, no Markdown.
 *
 * Split rather than one blob because the UI shows `who` more prominently --
 * the human consequence is the part that persuades somebody to fix it.
 */
export interface Explanation {
  what: string
  who: string
}

/** Contract 2.2: the corrected code, and every guess that went into it. */
export interface Fix {
  /** For syntax highlighting. */
  language: 'html' | 'css'
  /** The corrected code, ready to copy. */
  snippet: string
  /**
   * May be empty, which means the fix involved no guessing.
   *
   * **A non-empty array must be shown beside the snippet** -- contract rule
   * 5, not collapsed and not behind a tooltip. Task 8.7 builds that, and the
   * reason it is a rule is that an invented `alt` text pasted in good faith
   * is worse than no `alt` text, because it looks finished.
   */
  assumptions: string[]
}

/** Contract 2.2: one accessibility finding. */
export interface Issue {
  /** Unique within one response, `<rule_id>-<index>`. Not stable across scans. */
  id: string
  /** axe-core's rule id, e.g. `image-alt`. */
  rule_id: string
  severity: Severity
  /** WCAG success criteria. May be empty for best-practice rules. */
  wcag: string[]
  reference_url: string
  /** CSS selector locating the element. */
  selector: string
  /** The offending element's outer HTML, truncated to 500 characters. */
  html: string
  /**
   * `null` when `explanations_available` is false.
   *
   * Contract rule 4: `explanation` and `fix` are null together or populated
   * together, never one without the other.
   */
  explanation: Explanation | null
  fix: Fix | null
}

/** Contract 2.1: always all five keys, zeroes included. */
export interface Summary {
  critical: number
  serious: number
  moderate: number
  minor: number
  total: number
}

/** Contract 2.1 and 2.3: one scanned page. */
export interface Report {
  /** The URL **after redirects** -- may differ from the one requested. */
  url: string
  /** `null` if the page has no `<title>`, which is itself an issue. */
  page_title: string | null
  /** ISO 8601, UTC. The frontend converts for display. */
  scanned_at: string
  scan_duration_ms: number
  explanations_available: boolean
  /**
   * Optional, not nullable: the key is **absent** rather than null when
   * explanations are available. That is why this is `?` and not `| null`.
   */
  explanations_unavailable_reason?: UnavailableReason
  summary: Summary
  /** May be empty. Empty means no *detectable* issues, not an accessible page. */
  issues: Issue[]
}

/** Contract 1. */
export interface Health {
  status: string
  version: string
}

/** Contract 3: one shape for every failure, at every status code. */
export interface ApiErrorBody {
  error: {
    code: ErrorCode
    /** Shown to the user as-is. Plain language, says what to do next. */
    message: string
    detail: string | null
  }
}
