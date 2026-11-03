# A11y-Lens frontend

React + TypeScript + Vite + Tailwind. Talks to `../backend` over the API in
`../docs/api-contract.md`.

## Running it

Two terminals, because the app is two programs.

**Terminal 1 — the backend:**

```
cd backend
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

**Terminal 2 — this:**

```
cd frontend
npm install          # first time only
cp .env.example .env # first time only, then fill in the access code
npm run dev
```

Then open http://localhost:5173.

The access code in `frontend/.env` must match `ACCESS_CODE` in
`backend/.env`, or every request comes back `unauthorized`.

## The commands

| Command | What it does |
|---|---|
| `npm run dev` | Dev server with live reload, on port 5173 |
| `npm run build` | Type-checks, then builds into `dist/` |
| `npm test` | Runs every test once |
| `npm run test:watch` | Re-runs tests as you edit |
| `npm run smoke` | Checks the API client against a **running** backend |
| `npm run contrast` | Prints the palette's measured contrast ratios |
| `npm run lint` | oxlint |

`npm test` never touches the network — `fetch` is stubbed, so the suite passes
with nothing else running. `npm run smoke` is the opposite: it needs the
backend up, which is why it is separate.

## What is where

```
src/
  api/
    types.ts      The contract's shapes, written by hand from the document
    client.ts     The only module that talks to the backend
  config.ts       Backend address and access code, from the environment
  index.css       Tailwind, and the palette (Tailwind v4 configures in CSS)
  App.tsx         A placeholder until task 8.0
  test/setup.ts   Runs before every test file
scripts/
  smoke.ts        The live check against a real backend
  contrast.py     Measures the palette
```

## Two things worth knowing

**The access code here is weaker than the one in the backend.** Vite compiles
`VITE_*` variables into the JavaScript the browser downloads, so anybody who
opens developer tools can read it. It keeps a forwarded link from being
casually usable; it is not protection against somebody who wants in. The
backend's `ANTHROPIC_API_KEY` is a real secret and never comes near this half.

**The palette is checked by a test.** `src/palette.test.ts` reads the colours
out of `index.css` and does the WCAG arithmetic, so a colour edited to
something that fails AA breaks the build instead of shipping. Run
`npm run contrast` to see the numbers.
