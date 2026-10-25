import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vite';

const root = fileURLToPath(new URL('.', import.meta.url));

/** The page is `export.html` in the source. The Pages folder needs `index.html`. */
const indexName = (): Plugin => ({
  name: 'caddis-export-index-name',
  enforce: 'post',
  generateBundle(_options, bundle) {
    const page = bundle['export.html'];
    if (!page) return;
    page.fileName = 'index.html';
    bundle['index.html'] = page;
    delete bundle['export.html'];
  },
});

// The export page is static: no inline script or style, no map, relative URLs so it works at any Pages path (R60).
export default defineConfig({
  root,
  base: './',
  plugins: [react(), indexName()],
  build: {
    outDir: fileURLToPath(new URL('../dist/export', import.meta.url)),
    emptyOutDir: true,
    assetsDir: 'assets',
    assetsInlineLimit: 0,
    modulePreload: { polyfill: false },
    sourcemap: false,
    rollupOptions: { input: fileURLToPath(new URL('./export.html', import.meta.url)) },
  },
});
