// Build and test both React routes in a disposable application.
// Run from the skill folder: node scripts/react-proof.mjs
import { spawn, spawnSync } from 'node:child_process';
import { cpSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:net';
import { stopPreview } from './lib/react-proof-cleanup.mjs';
import { proofIndexHtml } from './lib/react-proof-page.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const tmp = mkdtempSync(join(tmpdir(), 'flow-studio-react-proof-'));
let preview;
let previewClosed;

function run(command, args, cwd = tmp) {
  const result = spawnSync(command, args, { cwd, stdio: 'inherit', shell: process.platform === 'win32' && command.toLowerCase().endsWith('npm.cmd'), env: process.env, timeout: 600_000 });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} ${args.join(' ')} exited ${result.status ?? result.signal}`);
}

async function freePort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close(() => resolvePort(address.port));
    });
  });
}

async function waitFor(url) {
  for (let i = 0; i < 100; i++) {
    if (preview.exitCode !== null) throw new Error(`vite preview exited ${preview.exitCode}`);
    try { if ((await fetch(url)).ok) return; } catch { /* server still starting */ }
    await new Promise(r => setTimeout(r, 100));
  }
  throw new Error(`vite preview did not start at ${url}`);
}

try {
  mkdirSync(join(tmp, 'src'));
  cpSync(join(root, 'react'), join(tmp, 'react'), { recursive: true });
  // The React files use ../src imports. Keep the real source path in the throwaway app.
  cpSync(join(root, 'src'), join(tmp, 'src'), { recursive: true });
  mkdirSync(join(tmp, 'templates'));
  for (const name of ['flow-studio.lib.mjs', 'flow-studio.lib.d.mts', 'flow-studio.css'])
    cpSync(join(root, 'templates', name), join(tmp, 'templates', name));
  mkdirSync(join(tmp, 'examples'));
  cpSync(join(root, 'examples', 'order-desk.json'), join(tmp, 'examples', 'order-desk.json'));
  writeFileSync(join(tmp, 'package.json'), JSON.stringify({
    private: true, type: 'module', scripts: { test: 'vitest run', build: 'tsc --noEmit && vite build' },
    dependencies: { react: '^18.3.1', 'react-dom': '^18.3.1' },
    devDependencies: { '@testing-library/react': '^16.0.0', '@types/react': '^18.3.0', '@types/react-dom': '^18.3.0', jsdom: '^26.0.0', playwright: '^1.51.0', typescript: '^5.0.0', vite: '^6.0.0', vitest: '^3.0.0' },
  }, null, 2));
  writeFileSync(join(tmp, 'index.html'), proofIndexHtml());
  writeFileSync(join(tmp, 'tsconfig.json'), JSON.stringify({ compilerOptions: {
    target: 'ES2022', useDefineForClassFields: true, lib: ['ES2022', 'DOM', 'DOM.Iterable'], module: 'ESNext', skipLibCheck: true,
    moduleResolution: 'Bundler', allowImportingTsExtensions: true, resolveJsonModule: true, isolatedModules: true,
    noEmit: true, jsx: 'react-jsx', strict: true, types: ['vitest/globals'],
  }, include: ['src', 'react', 'templates'], exclude: ['src/**/*.test.ts'] }, null, 2));
  writeFileSync(join(tmp, 'src', 'App.tsx'), "import { FlowStudioView } from '../react/index.ts';\nimport model from '../examples/order-desk.json';\nimport '../templates/flow-studio.css';\nimport type { Model } from './model.ts';\nexport default function App() { return <FlowStudioView model={model as Model} />; }\n");
  writeFileSync(join(tmp, 'src', 'main.tsx'), "import { StrictMode } from 'react';\nimport { createRoot } from 'react-dom/client';\nimport App from './App.tsx';\ncreateRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);\n");
  console.log(`Proof app: ${tmp}`);
  // The browser checks launch a real browser. On Windows and when FLOW_STUDIO_CHANNEL is set,
  // check.mjs uses a system browser (Edge or the named channel), so the Playwright browser
  // download is skipped there. Everywhere else, let npm fetch Playwright's own browser, or the
  // checks would fail on a clean machine that never downloaded one.
  if (process.env.FLOW_STUDIO_CHANNEL || process.platform === 'win32') process.env.PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD ??= '1';
  process.env.npm_config_cache = join(tmp, '.npm-cache');
  run(process.platform === 'win32' ? 'npm.cmd' : 'npm', ['install', '--no-audit', '--no-fund']);
  run(process.execPath, [join(tmp, 'node_modules', 'vitest', 'vitest.mjs'), 'run', 'react/FlowStudioView.test.tsx', 'react/native/native.test.tsx', '--environment', 'jsdom']);
  run(process.execPath, [join(tmp, 'node_modules', 'typescript', 'bin', 'tsc'), '--noEmit']);
  run(process.execPath, [join(tmp, 'node_modules', 'vite', 'bin', 'vite.js'), 'build']);
  const port = await freePort();
  const address = `http://127.0.0.1:${port}/`;
  preview = spawn(process.execPath, [join(tmp, 'node_modules', 'vite', 'bin', 'vite.js'), 'preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: tmp, stdio: 'inherit' });
  previewClosed = new Promise(resolve => preview.once('close', resolve));
  await waitFor(address);
  const checkArgs = [join(root, 'scripts', 'check.mjs'), address, '--out', join(tmp, 'check-out'), '--skip', 'hostile'];
  if (process.env.FLOW_STUDIO_CHANNEL || process.platform === 'win32') checkArgs.push('--channel', process.env.FLOW_STUDIO_CHANNEL ?? 'msedge');
  run(process.execPath, checkArgs, tmp);
  console.log('React proof passed.');
} catch (error) {
  console.error(`React proof failed: ${error.message}`);
  process.exitCode = 1;
} finally {
  await stopPreview(preview, previewClosed);
  rmSync(tmp, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
}
