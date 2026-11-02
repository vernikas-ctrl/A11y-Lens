# A11y Lens – project rules
## What this is
Web app: user enters a URL, backend scans it with Playwright + axe-core,
Claude API explains issues and suggests code fixes as JSON.

## Stack
- frontend/: React + TypeScript + Tailwind + Vite (deploy: Vercel)
- backend/: Python 3.14 + FastAPI + Playwright (deploy: host chosen in Phase 10 —
  a scan peaks near 859MB, so a 512MB free tier is not enough)

## Rules
- Work in small steps. Related tasks may share a branch and PR.
- Always plan first and wait for my approval before writing code.
- Every feature gets tests. Run all tests before saying a task is done.
- Never put API keys in code. Use .env and keep .env.example updated.
- Block scanning of localhost and private IP ranges (SSRF protection).
- After each task, explain in 5 bullet points what you changed and why,
  in simple language, and add any important decision to DECISIONS.md.
- The app itself must meet WCAG AA (contrast, labels, keyboard, focus).


# Project Instructions

## General Rules
- Understand the existing code before changing anything.
- Never duplicate existing functionality.
- Keep code clean and maintainable.

## GitHub Rules
- Never merge pull requests without my permission.
- Explain changes before committing.
- Never overwrite existing work.

## Communication
- Explain technical concepts in simple language.
- Tell me whenever you need my input.
- Don't claim something is complete unless verified.
