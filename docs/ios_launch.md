# Sharks Softball Dashboard - iOS Launch SOP

This document describes how to launch the Sharks Softball Dashboard as an iOS application.

## 🚀 Option 1: The Immediate Launch (PWA)
This is the fastest way to get the app on your phone. It feels exactly like a native app and works immediately.

1.  **Deploy your web app** to your public URL (e.g., via Nginx or Vercel).
2.  Open **Safari** on your iPhone.
3.  Navigate to your dashboard URL.
4.  Tap the **Share** button (Square with Up Arrow) in the bottom navigation bar.
5.  Scroll down to find and tap **"Add to Home Screen"**.
6.  Tap **Add** in the top right corner.
7.  The "Sharks" icon will now appear on your home screen. When launched, it will open in **standalone mode** (no browser address bar).

## 🛠️ Option 2: The Native Build (Capacitor)
If you have access to a Mac with Xcode, you can build a true native iOS package.

1.  **Sync Web Assets**: Ensure your latest code is built and synced to the native project:
    ```bash
    cd client
    npm run build
    npx cap sync ios
    ```
2.  **Open in Xcode**:
    ```bash
    npx cap open ios
    ```
3.  **Deploy to Device**:
    - Select your iPhone in the Xcode device selector.
    - Click the **Run** button (Triangle icon).
    - Note: You may need a free Apple Developer account to "Trust" the app on your phone.

## 🎨 Asset Management
The app uses the following icons from your `public/` folder:
- `pwa-192x192.png`: Main app icon and `apple-touch-icon`.
- `pwa-512x512.png`: High-resolution assets.
- `sharks-logo-round.png`: Web favicon.
