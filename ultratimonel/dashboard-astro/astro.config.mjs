// @ts-check
import { defineConfig } from 'astro/config';
import react from '@astrojs/react';

// ADR-2/ADR-4: the dev proxy targets the legacy Python server (default 3005,
// override via ULTRATIMONEL_DASHBOARD_PORT). Astro does not expose server.proxy;
// the proxy is configured through vite.server.proxy and applies to astro dev only.
const apiTarget = `http://127.0.0.1:${process.env.ULTRATIMONEL_DASHBOARD_PORT || '3005'}`;

// https://astro.build/config
export default defineConfig({
  output: 'static',
  integrations: [react()],
  server: { host: '127.0.0.1', port: 3006 },
  vite: {
    server: {
      proxy: {
        '/api': { target: apiTarget, changeOrigin: true },
      },
    },
  },
});
