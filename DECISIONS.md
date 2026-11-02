# Decisions

Why A11y-Lens is built the way it is. Newest last. Each entry records what was
decided, why, and what it costs — including the decisions that turned out to
have a downside, because those are the interesting ones.

---

## 2026-11-01 — Build it as a web app, not a browser extension

**Decided:** A web app where you enter a URL, with a Python backend that scans
the page.

**Why:** A browser extension was considered first and would have been simpler —
no server, no hosting, no running costs — because it can read the page you are
already on. It was rejected because an extension is awkward to share: a
reviewer would have to download the code and load an unpacked extension in
developer mode. A web app is a link.

**Cost:** A server is now required, which means hosting, cold starts, and
protecting against people feeding it malicious URLs. All of Phase 3 exists
because of this decision.

---

## 2026-11-01 — A11y-Lens is a portfolio piece

**Decided:** The primary audience is someone assessing my work; the secondary
audience is developers fixing their own site.

**Why:** It sets the priorities. A reviewer will click the link, look at the
interface, tab through it with the keyboard, read the README, and skim the
commit history. They will not read the scanner's internals.

**Cost:** Polish and a demo that always works outrank backend depth. Features
that would impress another engineer but that nobody can see — a job queue, a
plugin system — are not worth building here.

---

## 2026-11-01 — Live scanning sits behind a shared access code

**Decided:** The demo page is public. Entering a URL and running a real scan
requires an access code.

**Why:** Every scan spends Claude API credits, and the budget is zero. An open
endpoint is an open tap: one person with a loop could empty the account
overnight.

**Cost:** This is obscurity, not security — links get forwarded, pasted into
chat, and screenshotted. So it does not remove the need for a hard spend
ceiling; it only removes drive-by traffic from bots and crawlers. Both are
being built (Phase 6).

**Consequence:** A reviewer cannot run a live scan without being given the
code, which conflicts with this being a portfolio piece. Resolved by making
the public demo page (task 8.1) a real saved report that renders instantly with
no backend call, so the work is visible in one click.

---

## 2026-11-01 — One page per scan, but do not design against crawling

**Decided:** A scan covers a single URL. No following links, no multi-page
crawling.

**Why:** Crawling multiplies scan time, API cost and complexity, and needs a
job queue and a database. None of that is affordable on a zero budget, and none
of it makes the tool more impressive to look at.

**Cost:** Low, as long as the API response is shaped to describe *one page*
rather than assuming there is only ever one. Noted in the API contract.

---

## 2026-11-01 — Free hosting tiers only

**Decided:** Render free tier for the backend, Vercel free tier for the
frontend, and a hard ceiling on Claude API spend.

**Why:** The budget is zero. This is not a preference.

**Cost:** Three real consequences. The backend sleeps when idle, so the first
scan after a quiet period is slow or fails — handled by the demo page and task
10.5. The free instance has 512MB of memory, which may not be enough for a
full Chromium browser — which is why Phase 1 tests that before anything is
built on the assumption. And explanation caching stops being an optimisation
and becomes load-bearing.

---

## 2026-11-02 — Claude returns a corrected snippet, with its guesses marked

**Decided:** Each fix is a corrected code snippet, not a general description of
the rule. Alongside it, Claude must return an explicit list of the assumptions
it made.

**Why:** A corrected snippet is immediately usable; a general pattern leaves the
reader to do the last and hardest step. But for some rules Claude *cannot* know
the right answer — given an image with no `alt` text, it has no idea what the
image shows, so the snippet necessarily contains an invention.

**Cost:** More work in three places: the API contract carries an `assumptions`
list, the prompt has to instruct Claude to declare what it invented, and the UI
has to display those assumptions where someone will read them before copying.

**Why it is worth it:** Someone assessing this tool will immediately try to
catch it being confidently wrong. Visibly handling that is worth more than
pretending it cannot happen.

---

## 2026-11-02 — Dropped the one-branch-one-PR-per-task rule

**Decided:** Related tasks may share a branch and a pull request.

**Why:** `CLAUDE.md` originally required one PR per feature. For the Phase 0
documentation tasks that meant four pull requests containing four Markdown
files that only make sense read together.

**Cost:** Larger PRs are harder to review, and the git history no longer maps
one commit to one task. Still using separate commits per task to keep some of
that traceability.

**Note:** Pull requests are still never merged without approval.

---

## 2026-11-02 — Python 3.14, pinned in a .python-version file

**Decided:** The backend runs Python 3.14, not the 3.12 originally written in
`CLAUDE.md`. `CLAUDE.md` has been updated to match.

**Why:** 3.14 was the only version installed, and it is also Render's own
default for new services, so it needed no install and no deviation from the
host. Render supports any released version from 3.7.3 onward, so 3.12 was
equally available — it just had no advantage. Playwright 1.64.1 and greenlet
3.5.6 both installed cleanly on 3.14.

**Cost:** None found. The risk considered was that a new Python might lack
compiled wheels for Playwright's dependencies; it did not.

**The part that actually matters:** local and Render must run the *same*
version. A `.python-version` file at the repo root pins it, so Render cannot
silently pick something else later. "Works on my machine, fails on deploy" is
nearly always this.
