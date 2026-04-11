import { useQuery } from '@tanstack/react-query';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import { useAppStore } from '@/store';
import type { GeoJSONGeometry } from '@/types/gameplay';

/**
 * Fetches and caches the hiding zone polygon for a given station.
 * Zone geometry is static per station, so results are cached with staleTime=Infinity.
 * Enabled only when a stationId is provided (non-null).
 */
export function useHidingZone(stationId: string | null): {
  hidingZone: GeoJSONGeometry | null;
  isLoading: boolean;
} {
  const gameId = useAppStore((s) => s.gameId);
  const enabled = gameId !== null && stationId !== null;

  const { data, isLoading } = useQuery({
    queryKey: ['hiding-zone', gameId, stationId],
    queryFn: async () => {
      const { data, error } = await api.GET('/games/{game_id}/hiding-zone', {
        params: {
          path: { game_id: gameId! },
          query: { station_id: stationId! },
          header: authHeader(),
        },
      });
      if (error) throw new Error('Hiding zone fetch failed');
      return data;
    },
    enabled,
    staleTime: Infinity,
    gcTime: 300_000,
  });

  return {
    hidingZone: (data?.hiding_zone as GeoJSONGeometry | undefined) ?? null,
    isLoading: enabled && isLoading,
  };
}
