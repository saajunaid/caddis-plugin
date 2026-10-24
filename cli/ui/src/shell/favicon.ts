import faviconUrl from '../brand/favicon.svg';
import faviconDotUrl from '../brand/favicon-dot.svg';

// Vite emits both files under assets/. The CSP allows them (img-src 'self').
export const faviconHref = (dot: boolean): string => (dot ? faviconDotUrl : faviconUrl);

export function setFavicon(dot: boolean): void {
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) {
    link = document.createElement('link');
    link.rel = 'icon';
    document.head.appendChild(link);
  }
  link.type = 'image/svg+xml';
  link.href = faviconHref(dot);
}
