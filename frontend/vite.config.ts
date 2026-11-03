/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
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
  },
})
