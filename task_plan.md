# Task Plan: PWA Conversion for Sharks Softball Analyzer

## Objective
Convert the Sharks Softball Analyzer web application into a Progressive Web App (PWA) with offline capabilities and an installation prompt.

## Phases

### Phase 1: Preparation & Audit
- [x] Task 1.1: Install `pwa-patterns` skill (Manually shimmed due to installer path issues)
- [x] Task 1.2: Audit React/Vite codebase for PWA readiness
- [x] Task 1.3: Map existing brand guidelines to PWA manifest
- [x] Task 1.4: Refactor `client/vite.config.js` with Workbox strategies (CacheFirst/NetworkFirst)
- [x] Task 1.5: Create `usePWAInstall` and `useOnlineStatus` hooks
- [ ] Task 1.6: Finalize UI integration in `App.jsx`

### Phase 2: Core PWA Assets
- Web App Manifest: Configured with Anchor Team colors (#046568 / #F7ECE1)
- Service Worker: Custom Workbox strategies (CacheFirst for assets, NetworkFirst for API)

### Phase 3: Engagement & Hooks
- UI Hooks: `usePWAInstall` and `useOnlineStatus` implemented
- Install Prompt: Button added to mobile menu and desktop header
- [ ] Register the Service Worker in `index.html` or `main.tsx`.

### Phase 4: Validation
- [ ] Verify manifest and service worker in a browser environment (simulated or real).
- [ ] Final SWOT analysis of the PWA implementation.
