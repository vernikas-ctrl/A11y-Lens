# axe-core, vendored

**Version 4.14.0.** Downloaded 2 November 2026 from
`https://cdn.jsdelivr.net/npm/axe-core@4.14.0/axe.min.js` (652,140 bytes).
Licence: Mozilla Public License 2.0, in `LICENSE` beside this file. Copyright
Deque Systems, Inc. Not our code, and not modified.

## Why it lives in the repo instead of being fetched

A scan would otherwise depend on a CDN being up at the moment someone clicks
the button, and would spend a second of every scan downloading 650KB that
never changes. Vendoring also means the test suite works with no internet.

## Updating it

Deliberately a manual step, because an axe-core update changes what the
scanner finds. Download the new version, replace both files, update the
version here and in `AXE_VERSION` in `backend/app/scanner.py`, then run the
tests: `backend/tests/test_scanner.py` asserts on rule ids, so a renamed or
retired rule will fail loudly rather than quietly reporting less.
