import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import { useAppStore } from '@/store';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { GeoJSONGeometry } from '@/types/gameplay';

/**
 * Fetches endgame exclusion data for a station + question cutoff, and syncs
 * the result into the gameplay store's endgameView state.
 *
 * Enabled only when both stationId and afterQuestion are non-null.
 * staleTime=0 because results change as new questions are answered.
 */
export function useEndgameExclusions(
  stationId: string | null,
  afterQuestion: number | null,
): { isLoading: boolean } {
  const gameId = useAppStore((s) => s.gameId);
  const enabled = gameId !== null && stationId !== null && afterQuestion !== null;

  const { data, isLoading } = useQuery({
    queryKey: ['endgame-exclusions', gameId, stationId, afterQuestion],
    queryFn: async () => {
      const { data, error } = await api.GET('/games/{game_id}/endgame-exclusions', {
        params: {
          path: { game_id: gameId! },
          query: { station_id: stationId!, after_question: afterQuestion! },
          header: authHeader(),
        },
      });
      if (error) throw new Error('Endgame exclusions fetch failed');
      return data;
    },
    enabled,
    staleTime: 0,
    gcTime: 300_000,
  });

  // Sync fetched data into the gameplay store
  useEffect(() => {
    if (!data || !stationId || afterQuestion === null) return;

    const lastEntry = data.entries[data.entries.length - 1];
    const store = useGameplayStore.getState();
    const hidingZone = data.hiding_zone as GeoJSONGeometry;
    const safeZone = data.safe_zone as GeoJSONGeometry;
    const totalExclusion = (lastEntry?.total_exclusion as GeoJSONGeometry | undefined) ?? null;

    if (
      store.endgameView?.stationId === stationId &&
      store.endgameView.afterQuestion === afterQuestion
    ) {
      // Already in endgame view for this station+cutoff — just update overlays
      store.updateEndgameView(safeZone, totalExclusion);
    } else {
      // First load or changed params — set the full endgame view
      store.setEndgameView({
        stationId,
        afterQuestion,
        hidingZone,
        safeZone,
        totalExclusion,
      });
    }
  }, [data, stationId, afterQuestion]);

  return { isLoading: enabled && isLoading };
}
