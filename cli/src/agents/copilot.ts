/** GitHub Copilot — detected, not yet driven. See stub.ts for why. */
import path from 'node:path';
import { createStubAdapter } from './stub.js';

export const copilotAdapter = createStubAdapter({
  id: 'copilot',
  name: 'GitHub Copilot',
  bins: ['copilot'],
  configPaths: [path.resolve(process.cwd(), '.github', 'copilot-instructions.md')],
  summary: 'merge the caddis pool into .github/ copilot instructions (v0.2)',
});
