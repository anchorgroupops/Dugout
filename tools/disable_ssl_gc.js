// Frida script to bypass SSL pinning in GameChanger Android app
// This script hooks common SSL verification methods used by OkHttp and TrustManager

function bypassOkHttp3() {
    try {
        const CertificatePinner = Java.use('okhttp3.CertificatePinner');
        CertificatePinner.check.overload('java.lang.String', 'java.util.List').implementation = function (hostname, peerCertificates) {
            // Skip verification
            console.log('[Frida] Bypassing okhttp3 CertificatePinner.check for', hostname);
            return;
        };
    } catch (e) {
        // OkHttp not present
    }
}

function bypassTrustManager() {
    try {
        const X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');
        const TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
        // Override checkServerTrusted to do nothing
        X509TrustManager.checkServerTrusted.implementation = function (chain, authType) {
            console.log('[Frida] Bypassing X509TrustManager.checkServerTrusted');
        };
        TrustManagerImpl.checkTrustedRecursive.implementation = function (certChain, authType, host) {
            console.log('[Frida] Bypassing TrustManagerImpl.checkTrustedRecursive');
            return certChain;
        };
    } catch (e) {
        // Not all classes may be present
    }
}

function main() {
    Java.perform(function () {
        console.log('[Frida] Starting SSL pinning bypass for GameChanger');
        bypassOkHttp3();
        bypassTrustManager();
        console.log('[Frida] Hooks installed');
    });
}

setImmediate(main);
