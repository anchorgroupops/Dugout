import { useState, useEffect } from 'react';

/**
 * Custom hook to handle Progressive Web App (PWA) installation.
 * Manages the beforeinstallprompt event and provides install triggers.
 */
export function usePWAInstall() {
  const [installPrompt, setInstallPrompt] = useState(null);
  const [canInstall, setCanInstall] = useState(false);
  const [isInstalled, setIsInstalled] = useState(false);

  useEffect(() => {
    const handleBeforeInstallPrompt = (e) => {
      // Prevent the mini-infobar from appearing on mobile
      e.preventDefault();
      // Stash the event so it can be triggered later.
      setInstallPrompt(e);
      setCanInstall(true);
      console.log('✅ PWA Install prompt stashed');
    };

    const handleAppInstalled = () => {
      // Clear the deferredPrompt so it can be garbage collected
      setInstallPrompt(null);
      setCanInstall(false);
      setIsInstalled(true);
      console.log('🎉 PWA was installed');
    };

    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
    window.addEventListener('appinstalled', handleAppInstalled);

    // Check if already in standalone mode
    if (window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true) {
      setIsInstalled(true);
    }

    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
      window.removeEventListener('appinstalled', handleAppInstalled);
    };
  }, []);

  const triggerInstall = async () => {
    if (!installPrompt) return;
    
    // Show the install prompt
    installPrompt.prompt();
    
    // Wait for the user to respond to the prompt
    const { outcome } = await installPrompt.userChoice;
    console.log(`User response to the install prompt: ${outcome}`);
    
    // We've used the prompt, and can't use it again, throw it away
    setInstallPrompt(null);
    setCanInstall(false);
  };

  return { canInstall, isInstalled, triggerInstall };
}
