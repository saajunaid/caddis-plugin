import { afterEach, describe, expect, it, vi } from 'vitest';
import { copyText } from '../../ui/src/shell/clipboard';

describe('copyText', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('a denied clipboard: the rejected promise is caught', () => {
    const denied = Promise.reject(new Error('NotAllowedError'));
    const caught = vi.spyOn(denied, 'catch');
    const writeText = vi.fn(() => denied);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    copyText('caddis');
    expect(writeText).toHaveBeenCalledWith('caddis');
    expect(caught).toHaveBeenCalledTimes(1);
    denied.then(undefined, () => undefined); // keep the old code's failure from leaking out of this test
  });

  it('no clipboard: nothing happens', () => {
    vi.stubGlobal('navigator', {});
    expect(() => copyText('caddis')).not.toThrow();
  });
});
