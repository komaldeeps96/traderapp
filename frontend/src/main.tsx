import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { installTestHooks } from '@/lib/testHooks';

import App from './App';
import './index.css';

installTestHooks();

const container = document.getElementById('root');
if (!container) throw new Error('#root is missing from index.html');

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
