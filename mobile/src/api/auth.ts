import { useAppStore } from '@/store';

/** Returns the auth header object for typed API calls. */
export function authHeader() {
  const { playerId, playerSecret } = useAppStore.getState();
  return { 'x-player-id': playerId!, 'x-player-secret': playerSecret! };
}
