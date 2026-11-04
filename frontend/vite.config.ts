/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

/**
 * The scanner's own copy of axe-core, which `src/a11y.test.tsx` imports so
 * the frontend is checked by exactly the engine that checks everybody else's
 * pages. It lives outside this project, and Vite refuses to serve anything
 * outside the root unless told otherwise.
 */
const VENDORED_AXE = fileURLToPath(
  new URL('../backend/app/vendor/axe-core', import.meta.url),
)

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  // **Only while testing.** Widening `fs.allow` for the dev server would let
  // it serve files from anywhere above the frontend -- including
  // `backend/.env` -- to anything that can reach localhost. It is granted to
  // one directory, and only in the mode that needs it.
  server: mode === 'test'
    ? { fs: { allow: ['.', VENDORED_AXE] } }
    : undefined,
  test: {
    // The tests render React components, which need something that behaves
    // like a browser. jsdom is that, in Node, without opening a real one.
    environment: 'jsdom',
    // Runs before every test file: see src/test/setup.ts.
    setupFiles: ['./src/test/setup.ts'],
    // `describe`, `it` and `expect` are imported explicitly in each test file
    // rather than injected as globals. One more import line per file, in
    // exchange for a reader being able to see where everything comes from --
    // the same reason the backend's tests import pytest rather than relying
    // on magic.
    globals: false,
    css: true,
    // Pinned, so the suite does not depend on whether the person running it
    // happens to have a .env file -- and so a real access code can never
    // influence a test result. The backend's conftest.py does the same thing
    // for the same reason.
    env: {
      VITE_API_BASE_URL: 'http://127.0.0.1:8000',
      VITE_ACCESS_CODE: '',
    },
  },
}))
