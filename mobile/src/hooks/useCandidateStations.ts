import { useQuery } from '@tanstack/react-query';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import { useAppStore } from '@/store';
import type { StopResponse } from '@/types/gameplay';

/**
 * Fetches candidate stations for the seeker endgame station picker.
 * Candidate stations are stops whose hiding zone is not fully covered by exclusions.
 * Enabled only when the seeker is actively picking a station.
 */
export function useCandidateStations(enabled: boolean): {
  stations: StopResponse[];
  isLoading: boolean;
} {
  const gameId = useAppStore((s) => s.gameId);
  const queryEnabled = enabled && gameId !== null;

  const { data, isLoading } = useQuery({
    queryKey: ['candidate-stations', gameId],
    queryFn: async () => {
      const { data, error } = await api.GET('/games/{game_id}/candidate-stations', {
        params: {
          path: { game_id: gameId! },
          query: { offset: 0, limit: 200 },
          header: authHeader(),
        },
      });
      if (error) throw new Error('Candidate stations fetch failed');
      return data;
    },
    enabled: queryEnabled,
    staleTime: 30_000,
    gcTime: 300_000,
  });

  return {
    stations: (data as StopResponse[] | undefined) ?? [],
    isLoading: queryEnabled && isLoading,
  };
}
