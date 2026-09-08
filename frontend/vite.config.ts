import { fileURLToPath, URL } from 'node:url';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    // Every IPv4 interface, so a phone or tablet on the same WiFi opens
    // http://<this-mac's-ip>:3000 and gets the dev server with hot reload
    // intact — Vite aims the HMR socket at whatever host served the page, so
    // there is nothing further to configure for the second device.
    //
    // 0.0.0.0 rather than `true` or "localhost": it still covers 127.0.0.1,
    // which the Playwright and health checks use, and "localhost" resolves to
    // ::1 on some machines, which makes those checks fail.
    host: '0.0.0.0',
    port: 3000,
    strictPort: true,
    // An IP literal is allowed unconditionally; a Bonjour name is not, and
    // that is the address that survives a DHCP lease change.
    allowedHosts: ['.local'],
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
    strictPort: true,
    allowedHosts: ['.local'],
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    restoreMocks: true,
  },
});
