import { QueryClientProvider } from '@tanstack/react-query';
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
  return (
    <QueryClientProvider client={queryClient}>
      <Stack>
        <Stack.Screen name="index" options={{ title: 'HideAndSeek' }} />
        <Stack.Screen name="create" options={{ title: 'Create Game' }} />
        <Stack.Screen name="join" options={{ title: 'Join Game' }} />
        <Stack.Screen name="lobby/[game_id]" options={{ title: 'Lobby' }} />
      </Stack>
    </QueryClientProvider>
  );
}
