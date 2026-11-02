# Scope: who A11y-Lens is for, and what "finished" means

## Who it is for

**Developers who have been told their site has accessibility problems and don't
know where to start** — people who can edit HTML and CSS, but who find
axe-core's raw output (`color-contrast: Element has insufficient color contrast
of 2.41:1`) technically correct and practically useless.

A second audience reads this repo rather than uses the app: someone assessing
my work. That is why `DECISIONS.md` exists and why the app has to pass its own
accessibility tests.

## What v1 must do to be finished

Every line here is checkable by someone who is not me.

1. **There is a public link** that can be sent to anyone.
2. **The demo page renders a real report instantly**, with the backend switched
   off entirely.
3. **Entering a URL with the access code produces a readable report, or a clear
   error, every time.** No blank screens, no raw status codes, no silent
   hangs — seven named error states, each saying what to do next.
4. **Every issue tells the reader what is broken, who it affects, and how to
   fix it**, with a corrected snippet they can copy.
5. **Anything Claude guessed is visibly marked as a guess**, where it will be
   read before the snippet is copied.
6. **Private and internal addresses are refused** — `localhost`, `127.0.0.1`,
   `10.x`, `169.254.169.254` — with tests proving it.
7. **A stranger cannot spend the API budget.** Live scanning needs the access
   code, and a hard daily ceiling stops spending even if the code leaks.
8. **A11y-Lens passes its own scan**: zero axe violations on its own interface,
   fully keyboard-operable, AA contrast throughout, usable at 200% zoom.
9. **Both test suites run automatically on every pull request**, and a broken
   test blocks it.
10. **The README gets a stranger from `git clone` to a working local app**
    without asking me anything.
11. **The cost of one scan is measured and written down**, along with what 100
    scans would cost.

## What it deliberately will not do

Stated so that scope cannot quietly grow:

1. **No user accounts and no login.** Access is one shared code.
2. **No saved history and no shareable report links.** Nothing is stored
   between requests; close the tab and the report is gone.
3. **No multi-page crawling.** One URL, one page, one report.
4. **No scanning of pages behind a login.** If a page needs a session,
   A11y-Lens sees whatever an anonymous visitor sees.
5. **No database.** Explanation caching lives in the server's memory and is
   emptied on restart.
6. **No downloadable report file.** Roughly one task to add later if wanted.

## The honest limit

Automated accessibility testing catches **roughly a third** of real
accessibility problems. Things no tool can judge — whether `alt` text actually
describes the image, whether a reading order makes sense, whether an error
message is comprehensible — need a human, and ideally a human who uses assistive
technology.

A clean A11y-Lens report means **no detectable issues**, not an accessible
page. The interface has to say so, not just this file.
