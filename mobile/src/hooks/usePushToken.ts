import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { useEffect } from 'react';
import { Platform } from 'react-native';

import { useAppStore } from '@/store';

type TokenProvider = 'apns' | 'fcm';

const provider: TokenProvider = Platform.OS === 'ios' ? 'apns' : 'fcm';

async function registerForPushNotifications(): Promise<string | null> {
  if (!Device.isDevice) {
    return null;
  }

  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('default', {
      name: 'Default',
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: [0, 250, 250, 250],
    });
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;

  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }

  if (finalStatus !== 'granted') {
    return null;
  }

  const deviceToken = await Notifications.getDevicePushTokenAsync();
  return deviceToken.data as string;
}

/**
 * Requests push notification permission, retrieves the native device token
 * (APNs on iOS, FCM on Android), and stores it in the app store.
 * Also listens for token rotation and updates the store accordingly.
 */
export function usePushToken(): void {
  useEffect(() => {
    void registerForPushNotifications().then((token) => {
      if (token) {
        useAppStore.getState().setPushToken(token, provider);
      }
    });

    const subscription = Notifications.addPushTokenListener((deviceToken) => {
      useAppStore.getState().setPushToken(deviceToken.data as string, provider);
    });

    return () => subscription.remove();
  }, []);
}
