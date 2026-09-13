import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { installTestHooks } from '@/lib/testHooks';

import App from './App';
import './index.css';

// Build-time constants, so a production bundle drops the hooks entirely.
if (import.meta.env.DEV || import.meta.env.VITE_TEST_HOOKS) installTestHooks();

const container = document.getElementById('root');
if (!container) throw new Error('#root is missing from index.html');

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
