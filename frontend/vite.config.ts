import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const proxyTarget = process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000';
const devHost = process.env.VITE_DEV_HOST || '127.0.0.1';
const devPort = Number(process.env.VITE_DEV_PORT || '5173');

export default defineConfig({
  plugins: [react()],
  server: {
    host: devHost,
    port: devPort,
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
});
