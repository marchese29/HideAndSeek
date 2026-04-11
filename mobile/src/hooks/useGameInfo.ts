import { useQuery } from '@tanstack/react-query';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import type { GameInfo } from '@/types/gameplay';

/**
 * Fetches static game info (map geometry, transit data, timing config) once on
 * game entry. Data never changes mid-game so it's cached with staleTime=Infinity.
 */
export function useGameInfo(gameId: string): {
  gameInfo: GameInfo | undefined;
  isLoading: boolean;
} {
  const { data, isLoading } = useQuery({
    queryKey: ['game-info', gameId],
    queryFn: async () => {
      const { data, error } = await api.GET('/games/{game_id}/info', {
        params: { path: { game_id: gameId }, header: authHeader() },
      });
      if (error) throw new Error('Failed to fetch game info');
      return data;
    },
    staleTime: Infinity,
  });

  return { gameInfo: data as GameInfo | undefined, isLoading };
}
