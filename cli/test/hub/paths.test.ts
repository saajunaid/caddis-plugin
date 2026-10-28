import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { hubDir, sessionsPath } from '../../src/hub/paths.js';

describe('paths', () => {
  it('sessionsPath is hubDir/sessions.json', () => {
    expect(sessionsPath('/h')).toBe(path.join(hubDir('/h'), 'sessions.json'));
  });
});
