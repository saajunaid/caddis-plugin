import { describe, expect, it } from 'vitest';
import { loadMotion, MOTION_KEY, saveMotion } from '../../ui/src/shell/motion';

const mem = () => {
  const m = new Map<string, string>();
  return { m, getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) };
};
const boom = {
  getItem: (): string | null => {
    throw new Error('blocked');
  },
  setItem: (): void => {
    throw new Error('blocked');
  },
};

describe('motion switch (logo animation)', () => {
  it('is on by default, also when the OS asks for reduced motion', () => {
    // The owner's server reports reduced motion by default; the switch, not the OS, decides.
    expect(loadMotion(mem())).toBe('on');
  });
  it('saves and loads off and on', () => {
    const s = mem();
    saveMotion('off', s);
    expect(s.m.get(MOTION_KEY)).toBe('off');
    expect(loadMotion(s)).toBe('off');
    saveMotion('on', s);
    expect(loadMotion(s)).toBe('on');
  });
  it('survives a throwing or missing storage and an odd value', () => {
    expect(() => saveMotion('off', boom)).not.toThrow();
    expect(loadMotion(boom)).toBe('on');
    expect(loadMotion(null)).toBe('on');
    const s = mem();
    s.setItem(MOTION_KEY, 'sideways');
    expect(loadMotion(s)).toBe('on');
  });
});
