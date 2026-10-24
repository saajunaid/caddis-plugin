import markUrl from '../brand/mark-small.svg';
import wordmarkUrl from '../brand/wordmark.svg';

/** The Pixel C mark and the CADDIS wordmark, with "hub" under it (as in the approved mockup). */
export function Logo(): JSX.Element {
  return (
    <span className="brand-logo">
      <img src={markUrl} alt="" width={36} height={36} className="brand-mark" />
      <span className="brand-stack">
        <img src={wordmarkUrl} alt="CADDIS" width={100} height={20} className="brand-wordmark" />
        <span className="brand-sub">hub</span>
      </span>
    </span>
  );
}
