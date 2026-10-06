import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pageUrl, skippedGroups } from './check-args.mjs';

test('pageUrl accepts served pages and local files', () => {
  assert.equal(pageUrl('http://127.0.0.1:8123/path'), 'http://127.0.0.1:8123/path');
  assert.equal(pageUrl('https://example.test/flow'), 'https://example.test/flow');
  assert.equal(pageUrl('file:///tmp/page.html'), 'file:///tmp/page.html');
  assert.match(pageUrl('page.html'), /^file:\/\//);
});

test('skip parser accepts only known groups', () => {
  assert.deepEqual([...skippedGroups('notes,playback,update,hostile')], ['notes', 'playback', 'update', 'hostile']);
  assert.throws(() => skippedGroups('safety'), /unknown skip group/);
});
