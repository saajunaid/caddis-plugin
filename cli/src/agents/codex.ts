/** OpenAI Codex — detected, not yet driven. See stub.ts for why. */
import os from 'node:os';
import path from 'node:path';
import { createStubAdapter } from './stub.js';

export const codexAdapter = createStubAdapter({
  id: 'codex',
  name: 'Codex',
  bins: ['codex'],
  configPaths: [path.join(os.homedir(), '.codex')],
  summary: 'merge the caddis pool into ~/.codex + AGENTS.md (v0.2)',
});
