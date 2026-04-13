import { authHeader } from '@/api/auth';
import { api } from '@/api/client';

/** Expand the hiding zone radius. Hider-only, one-time use. Returns true on success. */
export async function expandHidingZone(gameId: string): Promise<boolean> {
  const { error } = await api.POST('/games/{game_id}/expand-hiding-zone', {
    params: {
      path: { game_id: gameId },
      header: authHeader(),
    },
  });
  return !error;
}
