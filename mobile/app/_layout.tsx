import { QueryClientProvider } from '@tanstack/react-query';
import { Stack } from 'expo-router';

import { queryClient } from '@/api/queryClient';

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
