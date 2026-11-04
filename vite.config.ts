import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    headers: {
      'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'SAMEORIGIN',
      'Referrer-Policy': 'strict-origin-when-cross-origin',
    },
    proxy: {
      '/api': {
        target: 'http://192.168.252.2:8000',
        changeOrigin: true,
      },
      '/docs': {
        target: 'http://192.168.252.2:8000',
        changeOrigin: true,
      },
      '/openapi.json': {
        target: 'http://192.168.252.2:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 950,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('three') || id.includes('@react-three')) {
              return 'three-vendor';
            }
            if (id.includes('recharts') || id.includes('d3-')) {
              return 'charts-vendor';
            }
            if (id.includes('gsap') || id.includes('framer-motion') || id.includes('lenis')) {
              return 'motion-vendor';
            }
            if (id.includes('react') || id.includes('@tanstack')) {
              return 'react-vendor';
            }
          }
          return undefined;
        },
      },
    },
  },
});
