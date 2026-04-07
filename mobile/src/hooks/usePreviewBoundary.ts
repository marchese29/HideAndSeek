import { useQuery } from '@tanstack/react-query';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import { useAppStore } from '@/store';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { GeoJSONGeometry } from '@/types/gameplay';

/** Quantize to 4 decimal places (~11 m) for cache-key stability. */
function quantize(value: number): number {
  return Math.round(value * 10_000) / 10_000;
}

/**
 * Fetches and caches the exclusion boundary preview for the currently selected
 * question slot. Responses are cached by question type + quantized seeker
 * location so browsing slots at the same position avoids redundant requests.
 */
export function usePreviewBoundary(): {
  boundary: GeoJSONGeometry | null;
  questionType: string | null;
} {
  const gameId = useAppStore((s) => s.gameId);
  const previewQuestion = useGameplayStore((s) => s.previewQuestion);
  const selfLocation = useGameplayStore((s) => s.selfLocation);

  const questionType = previewQuestion?.question_type ?? null;
  const slotIndex = previewQuestion?.slot_index ?? null;
  const customDistance = previewQuestion?.custom_distance ?? null;

  const lat = selfLocation ? quantize(selfLocation.coordinates.coordinates[1]) : null;
  const lng = selfLocation ? quantize(selfLocation.coordinates.coordinates[0]) : null;

  const enabled =
    gameId !== null &&
    previewQuestion !== null &&
    selfLocation !== null &&
    questionType !== 'thermometer' &&
    lat !== null &&
    lng !== null;

  const { data } = useQuery({
    queryKey: ['preview-boundary', gameId, questionType, slotIndex, lat, lng, customDistance],
    queryFn: async () => {
      const { data, error } = await api.GET('/games/{game_id}/questions/preview', {
        params: {
          path: { game_id: gameId! },
          query: {
            question_type: questionType as 'radar' | 'thermometer' | 'matching' | 'measuring',
            slot_index: slotIndex!,
            lat: selfLocation!.coordinates.coordinates[1],
            lng: selfLocation!.coordinates.coordinates[0],
            custom_distance: customDistance,
          },
          header: authHeader(),
        },
      });
      if (error) throw new Error('Preview fetch failed');
      return data;
    },
    enabled,
    gcTime: 120_000,
  });

  return {
    boundary: (data?.boundary as GeoJSONGeometry | undefined) ?? null,
    questionType,
  };
}
