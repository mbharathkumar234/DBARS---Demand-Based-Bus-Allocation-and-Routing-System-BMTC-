import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  // appId is the installed-app identity on Android, not branding: changing it
  // makes an existing install a different app and needs the native project
  // regenerated, so the rename stops at the display name.
  appId: 'com.bmtc.app',
  appName: 'DBARS',
  webDir: 'dist',
  android: {
    allowMixedContent: true,
    backgroundColor: '#0a1628'
  },
  plugins: {
    SplashScreen: {
      launchAutoHide: true,
      androidSplashResourceName: 'splash',
      backgroundColor: '#0a1628'
    }
  }
};

export default config;
