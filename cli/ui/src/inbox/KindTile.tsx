import { AlertTriangle, Ban, Check, GitMerge, OctagonAlert, ShieldCheck, User } from 'lucide-react';
import type { ItemKind } from './derive';

type Kind = ItemKind | 'resolved';

const TILE: Record<Kind, { Icon: typeof User; tone: string }> = {
  waiting: { Icon: User, tone: 'cyan' },
  'owner-gate': { Icon: ShieldCheck, tone: 'amber' },
  blocked: { Icon: Ban, tone: 'violet' },
  'blocked-merge': { Icon: GitMerge, tone: 'pink' },
  coordinator: { Icon: OctagonAlert, tone: 'red' },
  hub: { Icon: AlertTriangle, tone: 'grey' },
  resolved: { Icon: Check, tone: 'grey' },
};

/** The coloured icon tile of an Inbox item: the kind at a glance. Decorative; the row text names the kind. */
export function KindTile({ kind }: { kind: Kind }): JSX.Element {
  const { Icon, tone } = TILE[kind];
  return (
    <span className={`kind-tile tile-${tone}`} aria-hidden="true">
      <Icon size={17} strokeWidth={2.2} />
    </span>
  );
}
