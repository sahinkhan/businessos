import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { demoApiPlugin } from './dev/demoApi';

export default defineConfig(({ command }) => {
  const demoEnabled =
    command === 'serve' &&
    process.env.BOS_WEB_DEMO_LOGIN === '1' &&
    process.env.NODE_ENV !== 'production' &&
    (!process.env.BOS_ENVIRONMENT || process.env.BOS_ENVIRONMENT === 'development');
  return {
    plugins: [
      react(),
      ...(demoEnabled ? [demoApiPlugin(process.env.BOS_WEB_DEMO_PASSWORD ?? '')] : []),
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 3000,
      host: demoEnabled ? '127.0.0.1' : '0.0.0.0',
    },
    build: {
      target: 'es2022',
      sourcemap: true,
      rollupOptions: {
        output: {
          manualChunks: {
            vendor: ['react', 'react-dom', 'react-router-dom'],
            icons: ['lucide-react'],
          },
        },
      },
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./tests/setup.ts'],
      css: false,
    },
  } as any;
});
