import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { stopPreview } from './react-proof-cleanup.mjs';

test('stopPreview waits for process closure before temporary files can be removed', async () => {
  const preview = new EventEmitter();
  preview.exitCode = null;
  preview.signalCode = null;
  preview.kill = () => true;
  const closed = new Promise(resolve => preview.once('close', resolve));
  let stopped = false;
  const stopping = stopPreview(preview, closed).then(() => { stopped = true; });
  await Promise.resolve();
  assert.equal(stopped, false);
  preview.emit('close', 0);
  await stopping;
  assert.equal(stopped, true);
});

test('stopPreview waits for close after process exit', async () => {
  const preview = new EventEmitter();
  preview.exitCode = 0;
  preview.signalCode = null;
  preview.kill = () => { throw new Error('already exited'); };
  const closed = new Promise(resolve => preview.once('close', resolve));
  let stopped = false;
  const stopping = stopPreview(preview, closed).then(() => { stopped = true; });
  await Promise.resolve();
  assert.equal(stopped, false);
  preview.emit('close', 0);
  await stopping;
  assert.equal(stopped, true);
});

test('stopPreview force-kills a child that ignores the first kill', async () => {
  const preview = new EventEmitter();
  preview.exitCode = null;
  preview.signalCode = null;
  const kills = [];
  preview.kill = signal => { kills.push(signal); if (signal === 'SIGKILL') preview.emit('close'); return true; };
  const closed = new Promise(resolve => preview.once('close', resolve));
  await stopPreview(preview, closed, 10);
  assert.deepEqual(kills, [undefined, 'SIGKILL']);
});
