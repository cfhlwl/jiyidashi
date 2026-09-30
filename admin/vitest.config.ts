import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'],
    exclude: ['tests/visual/**', 'node_modules/**'],
    passWithNoTests: false,
  },
})
