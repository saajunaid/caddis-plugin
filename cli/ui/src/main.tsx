import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { captureTab } from './api';
import './fonts.generated.css';
import './brand/brand.css';
import './theme.css';
import './pages.css';

// Once, before the first request: take the tab token from the URL fragment and remove the fragment.
captureTab();

const root = document.getElementById('root');
if (root) createRoot(root).render(<StrictMode><App /></StrictMode>);
