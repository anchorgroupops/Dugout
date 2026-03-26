# Sharks Softball Dashboard - iOS Launch SOP

This document describes how to launch the Sharks Softball Dashboard as an iOS application.

## 🚀 Option 1: The Immediate Launch (PWA)

This is the fastest way to get the app on your phone. It feels exactly like a native app and works immediately.

1. **Expose Dev Server**: Ensure `package.json` has `vite --host` (I've already updated this).
1. **Start Dev Server**:

```bash
cd client
npm run dev
```

1. **Local URL**: Open Safari on your iPad and enter the following IP address (ensure the iPad is on the same WiFi):

    - **Local LAN**: `http://192.168.7.158:5173`
    - **Tailscale**: `http://100.119.215.43:5173`

1. **Add to Home Screen**:

    - Tap the **Share** button (Square with Up Arrow) in Safari.
    - Scroll down to find and tap **"Add to Home Screen"**.
    - Tap **Add** in the top right corner.
    - The "Sharks" icon will now appear on your home screen. When launched, it will open in **standalone mode** (no browser address bar).

## 🛠️ Option 2: Production Launch (Standalone Deployment)

Once you are ready for everyone to use it, you can deploy it to a public URL.

### 🌐 Method A: Tailscale Funnel (Easiest)
1. **Enable Funnel**: Visit your Tailscale console and enable Funnel for this node:
   [Enable Funnel](https://login.tailscale.com/f/funnel?node=n4h6gpX3y511CNTRL)
2. **Run Funnel**:
   ```bash
   tailscale funnel 5173
   ```
3. **Public URL**: You will receive a `tailscale.net` URL that works from anywhere.

### 🏠 Method B: Raspberry Pi (On-Premise)
Deploy to the Sharks' dedicated server (`dori-pi`):
1. **Sync Assets**: Ensure the project is synced via Syncthing.
2. **Launch Docker**:
   ```bash
   ssh joely@192.168.7.222 "cd Repos/Personal/Softball && docker-compose -f docker-compose.sharks.yml up -d --build"
   ```
3. **Internal URL**: `http://192.168.7.222:3000`

### ☁️ Method C: Vercel (Cloud)
1. **Run NPX**:
   ```bash
   npx vercel --prod
   ```

If you have access to a Mac with Xcode, you can build a true native iOS package.

1. **Sync Web Assets**: Ensure your latest code is built and synced to the native project:

```bash
cd client
npm run build
npx cap sync ios
```

1. **Open in Xcode**:

```bash
npx cap open ios
```

1. **Deploy to Device**:
    - Select your iPhone in the Xcode device selector.
    - Click the **Run** button (Triangle icon).
    - Note: You may need a free Apple Developer account to "Trust" the app on your phone.

## 🎨 Asset Management

The app uses the following icons from your `public/` folder:

- `pwa-192x192.png`: Main app icon and `apple-touch-icon`.
- `pwa-512x512.png`: High-resolution assets.
- `sharks-logo-round.png`: Web favicon.
