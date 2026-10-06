import test from 'node:test';
import assert from 'node:assert/strict';
import { proofIndexHtml } from './react-proof-page.mjs';

test('proof page supplies an inline favicon so the browser makes no missing-file request', () => {
  const html = proofIndexHtml();
  assert.match(html, /<link rel="icon" href="data:,">/);
  assert.match(html, /<script type="module" src="\/src\/main\.tsx"><\/script>/);
});
