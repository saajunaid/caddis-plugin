import { describe, expect, it } from 'vitest';
import { hubUpdatedTo } from '../../ui/src/useHubState';

describe('hubUpdatedTo (reload a tab after a hub update)', () => {
  it('a different version from the first one seen: reload to it', () => {
    expect(hubUpdatedTo('0.4.97', '0.4.98')).toBe('0.4.98');
  });

  it('the same version: no reload', () => {
    expect(hubUpdatedTo('0.4.98', '0.4.98')).toBeNull();
  });

  it('no first version yet, or a missing or empty one: no reload', () => {
    expect(hubUpdatedTo(null, '0.4.98')).toBeNull();
    expect(hubUpdatedTo('0.4.98', undefined)).toBeNull();
    expect(hubUpdatedTo('0.4.98', '')).toBeNull();
  });
});
