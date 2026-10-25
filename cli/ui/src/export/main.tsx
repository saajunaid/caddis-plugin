import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import type { ExportData } from '../../../src/hub/export/data';
import '../fonts.generated.css';
import '../brand/brand.css';
import '../theme.css';
import '../pages.css';
import './export.css';
import { ExportApp } from './ExportApp';

/** The data block the export command wrote into the page (R60). It is JSON text, never script. */
function readData(): ExportData | null {
  try {
    const text = document.getElementById('caddis-export-data')?.textContent;
    const parsed: unknown = text ? JSON.parse(text) : null;
    return parsed && typeof parsed === 'object' && (parsed as { schema?: unknown }).schema === 1 ? (parsed as ExportData) : null;
  } catch {
    return null;
  }
}

const root = document.getElementById('root');
if (root) {
  const data = readData();
  createRoot(root).render(
    <StrictMode>
      {data ? <ExportApp data={data} /> : <p className="page-subtitle" data-testid="ex-no-data">This page has no roadmap data.</p>}
    </StrictMode>,
  );
}
