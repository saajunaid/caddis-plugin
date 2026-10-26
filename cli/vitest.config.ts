import { availableParallelism } from 'node:os';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['test/**/*.test.ts'],
    environment: 'node',
    // Cap the workers at 8: one per core slows a shared machine. Never more than the cores: a 4-core CI runner
    // with 8 workers times out the fsync-heavy hub tests.
    maxWorkers: Math.min(8, Math.max(1, availableParallelism() - 1)),
    restoreMocks: true,
    // A run that leaves a caddis folder in the temp folder fails (tidy v2 Phase 5).
    globalSetup: ['./test/globalTempGuard.ts'],
  },
});
