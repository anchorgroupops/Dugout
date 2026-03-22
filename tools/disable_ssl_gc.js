// Frida script to bypass SSL pinning in GameChanger Android app
// Hooks common verification paths for OkHttp, TrustManager, and SSLContext.

function tryHook(label, fn) {
    try {
        fn();
        console.log(`[Frida] Hooked ${label}`);
    } catch (e) {
        // Class/method not present on this device/app build
    }
}

function bypassOkHttp() {
    tryHook('okhttp3.CertificatePinner.check(String, List)', () => {
        const CertificatePinner = Java.use('okhttp3.CertificatePinner');
        CertificatePinner.check.overload('java.lang.String', 'java.util.List').implementation = function (hostname, peerCertificates) {
            console.log('[Frida] Bypassing okhttp3 CertificatePinner.check for', hostname);
            return;
        };
    });

    tryHook('okhttp3.CertificatePinner.check(String, Certificate)', () => {
        const CertificatePinner = Java.use('okhttp3.CertificatePinner');
        CertificatePinner.check.overload('java.lang.String', 'java.security.cert.Certificate').implementation = function (hostname, cert) {
            console.log('[Frida] Bypassing okhttp3 CertificatePinner.check(cert) for', hostname);
            return;
        };
    });

    // OkHttp 4 (Kotlin) method name
    tryHook('okhttp3.CertificatePinner.check$okhttp', () => {
        const CertificatePinner = Java.use('okhttp3.CertificatePinner');
        CertificatePinner['check$okhttp'].implementation = function (hostname, peerCertificates, callback) {
            console.log('[Frida] Bypassing okhttp3 CertificatePinner.check$okhttp for', hostname);
            return;
        };
    });

    tryHook('okhttp3.internal.tls.OkHostnameVerifier.verify', () => {
        const OkHostnameVerifier = Java.use('okhttp3.internal.tls.OkHostnameVerifier');
        OkHostnameVerifier.verify.overload('java.lang.String', 'javax.net.ssl.SSLSession').implementation = function () {
            return true;
        };
    });
}

function bypassTrustManager() {
    tryHook('X509TrustManager.checkServerTrusted', () => {
        const X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');
        X509TrustManager.checkServerTrusted.implementation = function () {
            return;
        };
    });

    tryHook('TrustManagerImpl.checkTrustedRecursive', () => {
        const TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
        TrustManagerImpl.checkTrustedRecursive.implementation = function (certChain, authType, host) {
            return certChain;
        };
    });
}

function bypassSSLContext() {
    tryHook('SSLContext.init', () => {
        const SSLContext = Java.use('javax.net.ssl.SSLContext');
        const X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');

        const TrustManager = Java.registerClass({
            name: 'com.gc.trustmanager.TrustAllManager',
            implements: [X509TrustManager],
            methods: {
                checkClientTrusted: function (chain, authType) { },
                checkServerTrusted: function (chain, authType) { },
                getAcceptedIssuers: function () { return []; }
            }
        });

        SSLContext.init.overload(
            '[Ljavax.net.ssl.KeyManager;',
            '[Ljavax.net.ssl.TrustManager;',
            'java.security.SecureRandom'
        ).implementation = function (km, tm, sr) {
            console.log('[Frida] Bypassing SSLContext.init');
            return this.init(km, [TrustManager.$new()], sr);
        };
    });
}

function main() {
    Java.perform(function () {
        console.log('[Frida] Starting SSL pinning bypass for GameChanger');
        bypassOkHttp();
        bypassTrustManager();
        bypassSSLContext();
        console.log('[Frida] Hooks installed');
    });
}

setImmediate(main);
