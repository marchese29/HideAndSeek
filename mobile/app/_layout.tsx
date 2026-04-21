import '@/background/locationTask';

import { QueryClientProvider } from '@tanstack/react-query';
import { useFonts } from 'expo-font';
import * as Notifications from 'expo-notifications';
import { Stack } from 'expo-router';

import { queryClient } from '@/api/queryClient';

Notifications.setNotificationHandler({
  handleNotification: () =>
    Promise.resolve({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
});

export default function RootLayout() {
  // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
  const [fontsLoaded] = useFonts({ DSEG7: require('../assets/fonts/DSEG7Classic-Regular.ttf') });

  if (!fontsLoaded) return null;

  return (
    <QueryClientProvider client={queryClient}>
      <Stack>
        <Stack.Screen name="index" options={{ title: 'HideAndSeek' }} />
        <Stack.Screen name="create" options={{ title: 'Create Game' }} />
        <Stack.Screen name="join" options={{ title: 'Join Game' }} />
        <Stack.Screen
          name="lobby/[game_id]"
          options={{ title: 'Lobby', headerBackVisible: false, gestureEnabled: false }}
        />
        <Stack.Screen
          name="game/[game_id]"
          options={{ title: 'Game', headerShown: false, gestureEnabled: false }}
        />
        <Stack.Screen
          name="recap"
          options={{ title: 'Game Over', headerBackVisible: false, gestureEnabled: false }}
        />
      </Stack>
    </QueryClientProvider>
  );
}
