import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../src/util/exec.js', () => ({ run: vi.fn() }));

import { listAgyPids, parseTasklistCsv, parsePgrep } from '../src/util/agyProcs.js';
import { run } from '../src/util/exec.js';

describe('parseTasklistCsv', () => {
  it('reads the PID of every agy.exe row', () => {
    const csv = [
      '"agy.exe","31160","Console","1","116,472 K"',
      '"agy.exe","3572","Console","1","148,360 K"',
    ].join('\r\n');
    expect(parseTasklistCsv(csv)).toEqual([31160, 3572]);
  });

  it('ignores other programs and the "no tasks" message', () => {
    expect(parseTasklistCsv('"python.exe","7460","Services","0","2,696 K"')).toEqual([]);
    expect(parseTasklistCsv('INFO: No tasks are running which match the specified criteria.')).toEqual([]);
    expect(parseTasklistCsv('')).toEqual([]);
  });
});

describe('parsePgrep', () => {
  it('reads one PID per line and skips junk', () => {
    expect(parsePgrep('123\n456\n\nnot-a-pid\n')).toEqual([123, 456]);
  });
});


describe('listAgyPids', () => {
  const original = process.platform;
  const mockRun = vi.mocked(run);
  const setPlatform = (value: string) => Object.defineProperty(process, 'platform', { value });
  afterEach(() => {
    setPlatform(original);
    mockRun.mockReset();
  });

  it('on Windows asks tasklist for agy.exe and returns its PIDs, with a timeout', async () => {
    setPlatform('win32');
    mockRun.mockResolvedValue({ ok: true, code: 0, stdout: '"agy.exe","31160","Console","1","1 K"', stderr: '' });
    expect(await listAgyPids()).toEqual([31160]);
    const [cmd, args, options] = mockRun.mock.calls[0]!;
    expect(cmd).toBe('tasklist');
    expect(args).toEqual(['/FI', 'IMAGENAME eq agy.exe', '/FO', 'CSV', '/NH']);
    expect(options).toMatchObject({ timeout: expect.any(Number) });
  });

  it('elsewhere asks pgrep for an exact agy match', async () => {
    setPlatform('linux');
    mockRun.mockResolvedValue({ ok: true, code: 0, stdout: '55\n', stderr: '' });
    expect(await listAgyPids()).toEqual([55]);
    expect(mockRun.mock.calls[0]![0]).toBe('pgrep');
    expect(mockRun.mock.calls[0]![1]).toEqual(['-x', 'agy']);
  });

  it('returns no PIDs when the lookup itself fails, so a missing tasklist never blocks an install', async () => {
    setPlatform('win32');
    mockRun.mockResolvedValue({ ok: false, code: 1, stdout: '', stderr: 'not found' });
    expect(await listAgyPids()).toEqual([]);
  });
});
