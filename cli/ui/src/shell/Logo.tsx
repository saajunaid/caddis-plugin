import markAnimUrl from '../brand/mark-anim.webp';
import markStillUrl from '../brand/mark-still.png';
import wordmarkUrl from '../brand/wordmark.svg';

/**
 * The woven ASCII fly and the CADDIS wordmark, with "hub" under it. The mark is as tall as the text block
 * (36 px). Both mark images are in the page; `html[data-motion]` (the footer Motion switch) shows one.
 */
export function Logo(): JSX.Element {
  return (
    <span className="brand-logo">
      <img src={markAnimUrl} alt="" width={36} height={36} className="brand-mark brand-mark-anim" />
      <img src={markStillUrl} alt="" width={36} height={36} className="brand-mark brand-mark-still" />
      <span className="brand-stack">
        <img src={wordmarkUrl} alt="CADDIS" width={100} height={20} className="brand-wordmark" />
        <span className="brand-sub">hub</span>
      </span>
    </span>
  );
}
