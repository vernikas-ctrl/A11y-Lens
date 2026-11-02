# A11y-Lens

A web app that finds accessibility problems on a web page and explains them in
plain language. You give it a URL; it opens that page in a real browser, scans
it with [axe-core](https://github.com/dequelabs/axe-core), and uses the Claude
API to turn each raw finding into something you can act on — what is wrong, who
it affects, and a corrected code snippet. Anything Claude had to guess is
marked as a guess, so you never paste in an invented `alt` text believing the
tool knew what the image showed.

**Status:** in development. See [TASKS.md](TASKS.md) for the plan.

## Stack

| | |
|---|---|
| `frontend/` | React + TypeScript + Tailwind + Vite — deploys to Vercel |
| `backend/` | Python 3.12 + FastAPI + Playwright — deploys to Render |

## Limits worth knowing

Automated tools catch roughly a third of real accessibility problems. A clean
report from A11y-Lens means no *detectable* issues, not an accessible page.
