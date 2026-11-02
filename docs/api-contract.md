# API contract

The agreement between `frontend/` and `backend/`. Written before either exists,
so the two halves can be built independently. **If this file and the code
disagree, the code is wrong until this file is deliberately changed.**

A response describes **exactly one page**. A future version may scan several
pages per request; when it does, it will wrap these objects in a list rather
than reshape them. Nothing in the frontend should assume "one page" means "no
page identity" — that is why every report carries its own `url`.

---

## 1. Health check

```
GET /health
```

No authentication. Used by the deploy host to know the service is alive, and
by the frontend to detect a sleeping backend.

**200**
```json
{ "status": "ok", "version": "0.1.0" }
```

---

## 2. Scan a page

```
POST /scan
Content-Type: application/json
X-Access-Code: <the shared access code>
```

The access code travels in a **header, not the URL**. URLs leak through browser
history, server logs and `Referer` headers; headers do not.

**Request body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `url` | string | yes | Must be `http` or `https` and have a hostname |

```json
{ "url": "https://example.com" }
```

### 2.1 Success — 200

```json
{
  "url": "https://example.com/",
  "page_title": "Example Domain",
  "scanned_at": "2026-11-02T10:30:00Z",
  "scan_duration_ms": 4812,
  "explanations_available": true,
  "summary": {
    "critical": 0,
    "serious": 2,
    "moderate": 1,
    "minor": 0,
    "total": 3
  },
  "issues": [ /* see 2.2 */ ]
}
```

| Field | Type | Notes |
|---|---|---|
| `url` | string | The URL **after redirects** — may differ from the request |
| `page_title` | string \| null | `null` if the page has no `<title>`, which is itself an issue |
| `scanned_at` | string | ISO 8601, UTC |
| `scan_duration_ms` | integer | How long the scan took, for the UI to set expectations |
| `explanations_available` | boolean | `false` when Claude was unavailable or the daily cap was reached — see 2.3 |
| `summary` | object | Counts per severity. Always all five keys, zeroes included, so the UI never branches on a missing key |
| `issues` | array | May be empty. Empty means no *detectable* issues, not an accessible page |

### 2.2 One issue

```json
{
  "id": "image-alt-0",
  "rule_id": "image-alt",
  "severity": "serious",
  "wcag": ["1.1.1"],
  "reference_url": "https://dequeuniversity.com/rules/axe/4.10/image-alt",
  "selector": "main > img:nth-child(2)",
  "html": "<img src=\"/logo.png\">",
  "explanation": {
    "what": "This image has no alt attribute, so assistive technology has nothing to announce in its place.",
    "who": "Someone using a screen reader hears only \"image\" or the filename, and loses whatever the picture conveys."
  },
  "fix": {
    "language": "html",
    "snippet": "<img src=\"/logo.png\" alt=\"Acme Corp logo\">",
    "assumptions": [
      "Assumed this image is the Acme Corp logo, based on the filename. Replace the alt text if it shows something else."
    ]
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | string | Unique **within this response**. `<rule_id>-<index>`. Used as a UI key; not stable across scans |
| `rule_id` | string | axe-core's rule id, e.g. `image-alt`, `color-contrast`, `label` |
| `severity` | enum | `critical` \| `serious` \| `moderate` \| `minor` — axe-core's own scale, not a custom one |
| `wcag` | array of string | Success criteria, e.g. `["1.4.3"]`. May be empty for best-practice rules with no WCAG mapping |
| `reference_url` | string | Documentation for the rule |
| `selector` | string | CSS selector locating the element |
| `html` | string | The offending element's outer HTML, truncated to 500 characters |
| `explanation` | object \| null | `null` when `explanations_available` is `false` |
| `fix` | object \| null | `null` when `explanations_available` is `false` |

**`explanation`** has exactly two fields, both plain prose, no Markdown:
`what` is wrong, and `who` it affects. Split rather than one blob because the UI
shows `who` more prominently — the human consequence is the part that persuades
someone to fix it.

**`fix`** has three fields:

- `language` — for syntax highlighting. `html` or `css`.
- `snippet` — the corrected code, ready to copy.
- `assumptions` — **array of strings, may be empty.** Each entry names
  something Claude invented because the source could not tell it. An empty
  array means the fix is mechanical and involves no guessing (a missing `lang`
  attribute, for instance). A non-empty array **must** be shown next to the
  snippet; the UI is not permitted to hide it behind a disclosure.

### 2.3 Degraded success — still 200

When Claude is unreachable or the daily spend cap is hit, the scan still
returns its findings. A partial report beats a failed one.

```json
{
  "url": "https://example.com/",
  "explanations_available": false,
  "explanations_unavailable_reason": "daily_limit_reached",
  "summary": { "critical": 0, "serious": 2, "moderate": 1, "minor": 0, "total": 3 },
  "issues": [
    {
      "id": "image-alt-0",
      "rule_id": "image-alt",
      "severity": "serious",
      "wcag": ["1.1.1"],
      "reference_url": "https://dequeuniversity.com/rules/axe/4.10/image-alt",
      "selector": "main > img:nth-child(2)",
      "html": "<img src=\"/logo.png\">",
      "explanation": null,
      "fix": null
    }
  ]
}
```

`explanations_unavailable_reason` is present **only** when
`explanations_available` is `false`. Values: `daily_limit_reached`,
`api_unavailable`.

---

## 3. Errors

One shape for every failure, at every status code.

```json
{
  "error": {
    "code": "blocked_address",
    "message": "That address points inside a private network, so A11y-Lens will not scan it.",
    "detail": "Hostname resolved to 127.0.0.1"
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `code` | enum | Stable, machine-readable. The frontend branches on this, never on `message` |
| `message` | string | Shown to the user as-is. Plain language, says what to do next |
| `detail` | string \| null | Extra context for debugging. May be shown in small print; never required |

### Error codes

| `code` | HTTP | When | What the message should convey |
|---|---|---|---|
| `invalid_url` | 400 | Not `http`/`https`, no hostname, unparseable | What a valid URL looks like |
| `blocked_address` | 400 | Resolves to a private, loopback, link-local or reserved IP | That this is deliberate, not a bug |
| `unauthorized` | 401 | Missing or wrong `X-Access-Code` | That a code is needed, and the demo page is available without one |
| `not_found` | 404 | No such route on this API | That there is nothing at that address |
| `method_not_allowed` | 405 | Route exists, wrong HTTP method | That the address does not take this kind of request |
| `rate_limited` | 429 | Too many requests from one address | How long to wait |
| `daily_limit_reached` | 429 | Global daily scan ceiling reached | That it resets tomorrow |
| `unreachable` | 502 | DNS failure, connection refused, TLS failure, 4xx/5xx from the target | That the page, not A11y-Lens, is the problem |
| `scan_timeout` | 504 | The page did not finish loading in time | That the page may be unusually slow |
| `internal_error` | 500 | Anything unanticipated | An apology and nothing technical |

**`not_found` and `method_not_allowed` were added in task 2.5.** The original
eight codes covered scanning failures but not "you asked for a route that does
not exist", which a web framework answers by default in its own format. Since
rule 1 says the frontend branches on `code` and never on `message`, every
response that can reach a client needs a code — including the boring ones.

**`daily_limit_reached` appears in two places on purpose.** If the cap is hit
*before* a scan starts, it is this 429 error. If it is hit *after* axe-core has
already found issues, the scan returns 200 with
`explanations_available: false` — because findings without explanations are
still worth showing.

---

## 4. Rules both halves must follow

1. **The frontend branches on `error.code`, never on `message`.** Messages get
   reworded; codes do not.
2. **`summary` always contains all five keys**, zeroes included.
3. **`issues` may be empty.** Empty is a valid, successful result and needs its
   own screen, with the one-third caveat.
4. **`explanation` and `fix` are `null` together or populated together.** Never
   one without the other.
5. **A non-empty `assumptions` array must be visible** beside the snippet. Not
   collapsed, not a tooltip.
6. **Timestamps are ISO 8601 in UTC.** The frontend converts for display.
7. **The backend never returns a bare string or array** at the top level —
   always an object, so fields can be added without breaking the contract.
