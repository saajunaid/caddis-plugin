import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['test/**/*.test.ts'],
    environment: 'node',
    restoreMocks: true,
    // A run that leaves a caddis folder in the temp folder fails (tidy v2 Phase 5).
    globalSetup: ['./test/globalTempGuard.ts'],
  },
});
