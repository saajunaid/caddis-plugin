import { AlertTriangle, RefreshCw, XOctagon } from 'lucide-react';
import type { HubState } from '../types';
import { useHubUpdatedTo } from '../useHubState';
import { bannersFor } from './bannerRules';

export function Banners({ state }: { state: HubState }): JSX.Element | null {
  const items = bannersFor(state);
  const updated = useHubUpdatedTo();
  if (items.length === 0 && !updated) return null;
  return (
    <div className="banners" role="region" aria-label="Warnings">
      {updated && (
        <div className="banner warn" role="status" data-testid="banner-hub-updated">
          <RefreshCw size={16} aria-hidden="true" />
          <span>caddis hub updated to {updated}, reloading</span>
        </div>
      )}
      {items.map((b) => (
        <div key={b.id} className={`banner ${b.tone}`} role="status" data-testid={`banner-${b.id}`}>
          {b.tone === 'bad' ? <XOctagon size={16} aria-hidden="true" /> : <AlertTriangle size={16} aria-hidden="true" />}
          <span>
            {b.text}
            {b.command && (
              <>
                {' '}
                <code className="cmd">{b.command}</code>
              </>
            )}
          </span>
        </div>
      ))}
    </div>
  );
}
