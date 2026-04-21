import { ExpoConfig, ConfigContext } from 'expo/config';

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: 'HideAndSeek',
  slug: 'hide-and-seek',
  owner: process.env.EAS_PROJECT_OWNER,
  scheme: 'hideandseek',
  platforms: ['ios', 'android'],
  extra: {
    eas: {
      projectId: process.env.EAS_PROJECT_ID,
    },
  },
  orientation: 'portrait',
  icon: './assets/icon.png',
  userInterfaceStyle: 'light',
  splash: {
    image: './assets/splash-icon.png',
    resizeMode: 'contain',
    backgroundColor: '#ffffff',
  },
  ios: {
    supportsTablet: true,
    bundleIdentifier: 'dev.marchese.hideandseek',
    infoPlist: {
      UIBackgroundModes: ['location'],
    },
  },
  android: {
    package: 'dev.marchese.hideandseek',
    googleServicesFile: process.env.GOOGLE_SERVICES_JSON ?? './google-services.json',
    adaptiveIcon: {
      backgroundColor: '#E6F4FE',
      foregroundImage: './assets/android-icon-foreground.png',
      backgroundImage: './assets/android-icon-background.png',
      monochromeImage: './assets/android-icon-monochrome.png',
    },
    config: {
      googleMaps: {
        apiKey: process.env.GOOGLE_MAPS_API_KEY ?? '',
      },
    },
    permissions: [
      'ACCESS_BACKGROUND_LOCATION',
      'FOREGROUND_SERVICE',
      'FOREGROUND_SERVICE_LOCATION',
    ],
  },
  plugins: [
    'expo-router',
    [
      'expo-location',
      {
        locationAlwaysAndWhenInUsePermission:
          'Allow HideAndSeek to use your location for gameplay.',
      },
    ],
    [
      'expo-notifications',
      {
        color: '#3498DB',
      },
    ],
  ],
});
