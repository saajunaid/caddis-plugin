import { defineConfig } from 'tsup';

export default defineConfig({
  entry: {
    cli: 'src/cli.ts',
    // One bundle per lane binary. They are tiny — each is a two-line entry over the
    // shared launcher — but npm needs a distinct file per `bin` name.
    'claude-oss': 'src/lanes/claude-oss.ts',
    'claude-glm': 'src/lanes/claude-glm.ts',
    'claude-deepseek': 'src/lanes/claude-deepseek.ts',
  },
  format: ['esm'],
  target: 'node20.19',
  platform: 'node',
  outDir: 'dist',
  clean: true,
  splitting: false,
  sourcemap: false,
  dts: false,
  // Single-file output for a fast `npx` cold start: the small, pure-JS deps are
  // inlined so the runtime resolves one file instead of walking node_modules.
  // execa (cross-spawn shells out via node_modules paths) and update-notifier
  // (spawns a detached child by path relative to its own module) MUST stay
  // external — bundling either one breaks it, on Windows especially.
  noExternal: ['commander', 'picocolors', '@clack/prompts', 'which'],
  external: ['execa', 'update-notifier'],
  // commander is CJS. Inlining it into an ESM bundle leaves esbuild's
  // `__require` shim with no `require` in scope, so its `require('events')`
  // throws "Dynamic require ... is not supported" at startup. Defining a real
  // require via createRequire makes the shim pick it up. Shebang stays first.
  banner: {
    js: [
      '#!/usr/bin/env node',
      "import { createRequire as __caddisCreateRequire } from 'node:module';",
      'const require = __caddisCreateRequire(import.meta.url);',
    ].join('\n'),
  },
});
