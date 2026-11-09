import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { hubLog, LOG_MAX_BYTES } from '../../src/hub/hubLog.js';
import { logPath } from '../../src/hub/paths.js';

let home: string;
beforeEach(() => {
  home = mkdtempSync(path.join(tmpdir(), 'caddis-hublog-'));
  vi.spyOn(process.stderr, 'write').mockImplementation(() => true);
});
afterEach(() => rmSync(home, { recursive: true, force: true }));

describe('hubLog', () => {
  it('appends one timestamped line per call, newlines flattened', () => {
    hubLog('first', home, () => Date.UTC(2026, 10, 8, 12, 0, 0));
    hubLog('second\nline', home, () => Date.UTC(2026, 10, 8, 12, 0, 1));
    expect(readFileSync(logPath(home), 'utf8')).toBe(
      '2026-11-08T12:00:00.000Z first\n2026-11-08T12:00:01.000Z second line\n',
    );
  });

  it('moves a full log to hub.log.1 and starts a new one', () => {
    hubLog('x', home);
    writeFileSync(logPath(home), 'a'.repeat(LOG_MAX_BYTES + 1));
    hubLog('fresh', home, () => 0);
    expect(readFileSync(`${logPath(home)}.1`, 'utf8')).toHaveLength(LOG_MAX_BYTES + 1);
    expect(readFileSync(logPath(home), 'utf8')).toBe('1970-01-01T00:00:00.000Z fresh\n');
  });

  it('never throws when the folder cannot be made', () => {
    const file = path.join(home, 'blocker');
    writeFileSync(file, '');
    expect(() => hubLog('x', file)).not.toThrow();
    expect(existsSync(logPath(file))).toBe(false);
  });
});
