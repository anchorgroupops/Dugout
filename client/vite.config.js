import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  server: {
    proxy: {
      '/api': 'http://localhost:5000',
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/react/') || id.includes('node_modules/react-dom/')) return 'vendor';
          if (id.includes('node_modules/lucide-react')) return 'icons';
        },
      },
    },
  },
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'script-defer',
      includeAssets: ['favicon.ico', 'apple-touch-icon.png', 'mask-icon.svg'],
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
        cleanupOutdatedCaches: true,
        clientsClaim: true,
        skipWaiting: true,
        // When a precached JS/CSS chunk fetch fails (404/503 — usually a stale
        // hash served from disk cache after a deploy), fall back to fetching
        // index.html. The page reload in main.jsx will then pull the fresh
        // manifest with the current hashes.
        navigateFallback: '/index.html',
        runtimeCaching: [
          {
            // JS/CSS chunks: NetworkFirst with 3s timeout. If network responds
            // (even with 404), we trust it over our cached copy. This prevents
            // the SW from serving a stale hash that the server has already
            // garbage-collected, which causes 503/404 cascades on deploy.
            urlPattern: ({ url, request }) =>
              (request.destination === 'script' || request.destination === 'style') &&
              /\/assets\/.+\.(js|css)$/.test(url.pathname),
            handler: 'NetworkFirst',
            options: {
              cacheName: 'js-chunks',
              networkTimeoutSeconds: 3,
              expiration: { maxEntries: 200, maxAgeSeconds: 7 * 24 * 60 * 60 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            // Cache static assets (fonts, images) with CacheFirst strategy
            urlPattern: ({ request }) => request.destination === 'image' || request.destination === 'font',
            handler: 'CacheFirst',
            options: {
              cacheName: 'static-assets',
              expiration: {
                maxEntries: 50,
                maxAgeSeconds: 30 * 24 * 60 * 60, // 30 Days
              },
            },
          },
          {
            // Cache announcer TTS clips with CacheFirst (1-year immutable after render)
            urlPattern: ({ url }) => url.pathname.startsWith('/announcer-clips/'),
            handler: 'CacheFirst',
            options: {
              cacheName: 'announcer-clips',
              expiration: {
                maxEntries: 300,
                maxAgeSeconds: 365 * 24 * 60 * 60,
              },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            // Walk-up music hooks — CacheFirst because hook clips are immutable
            // (the URL contains the song slug). Keeps the bumper instant even
            // when field Wi-Fi drops mid-game.
            urlPattern: ({ url }) =>
              url.pathname.startsWith('/audio/music/') ||
              url.pathname.startsWith('/audio/walkup/'),
            handler: 'CacheFirst',
            options: {
              cacheName: 'walkup-music',
              expiration: {
                maxEntries: 200,
                maxAgeSeconds: 365 * 24 * 60 * 60,
              },
              cacheableResponse: { statuses: [0, 200, 206] },
              rangeRequests: true,
            },
          },
          {
            // Cache API data (GameChanger stats, SWOT, lineups) with NetworkFirst strategy
            urlPattern: ({ url }) => url.pathname.startsWith('/api/') || url.pathname.endsWith('.json'),
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-data',
              networkTimeoutSeconds: 5,
              expiration: {
                maxEntries: 100,
                maxAgeSeconds: 24 * 60 * 60, // 24 Hours
              },
              cacheableResponse: {
                statuses: [0, 200],
              },
            },
          },
        ],
      },
      manifest: {
        name: 'The Sharks - Softball Dashboard',
        short_name: 'Sharks',
        description: 'Strategy & Training Aid for The Sharks (PCLL)',
        theme_color: '#046568',
        background_color: '#060d1c',
        display: 'standalone',
        orientation: 'portrait',
        scope: '/',
        start_url: '/',
        icons: [
          {
            src: 'pwa-192x192.png',
            sizes: '192x192',
            type: 'image/png'
          },
          {
            src: 'pwa-512x512.png',
            sizes: '512x512',
            type: 'image/png'
          },
          {
            src: 'pwa-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'any maskable'
          }
        ]
      },
      devOptions: {
        enabled: mode !== 'production'
      }
    })
  ],
}))
