import { useQuery } from '@tanstack/react-query';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import { useAppStore } from '@/store';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { GeoJSONGeometry, TentaclePOIPreviewResponse } from '@/types/gameplay';

/** Quantize to 4 decimal places (~11 m) for cache-key stability. */
function quantize(value: number): number {
  return Math.round(value * 10_000) / 10_000;
}

export interface PreviewBoundaryInput {
  questionType: string;
  slotIndex: number;
  customDistance: number | null;
}

export interface PreviewBoundaryResult {
  boundary: GeoJSONGeometry | null;
  questionType: string | null;
  tentaclePois: TentaclePOIPreviewResponse[] | null;
}

/**
 * Parameterized variant — drives the preview from caller-supplied state instead
 * of `gameplayStore.previewQuestion`. Used by the question picker modal so it
 * doesn't have to mutate the global preview state (which would also drive the
 * legacy `'browse'` overlay on the underlying main map).
 */
export function usePreviewBoundaryFor(input: PreviewBoundaryInput | null): PreviewBoundaryResult {
  const gameId = useAppStore((s) => s.gameId);
  const selfLocation = useGameplayStore((s) => s.selfLocation);

  const questionType = input?.questionType ?? null;
  const slotIndex = input?.slotIndex ?? null;
  const customDistance = input?.customDistance ?? null;

  const lat = selfLocation ? quantize(selfLocation.coordinates.coordinates[1]) : null;
  const lng = selfLocation ? quantize(selfLocation.coordinates.coordinates[0]) : null;

  const enabled =
    gameId !== null &&
    input !== null &&
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
            question_type: questionType as
              | 'radar'
              | 'thermometer'
              | 'matching'
              | 'measuring'
              | 'tentacles',
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
    tentaclePois: (data?.tentacle_pois as TentaclePOIPreviewResponse[] | undefined) ?? null,
  };
}

/**
 * Fetches and caches the exclusion boundary preview for the currently selected
 * question slot in the legacy in-belt picker. Reads from
 * `gameplayStore.previewQuestion`; thin wrapper over `usePreviewBoundaryFor`.
 *
 * Slated for removal in muo.4 along with the in-belt `ParamPicker` path.
 */
export function usePreviewBoundary(): PreviewBoundaryResult {
  const previewQuestion = useGameplayStore((s) => s.previewQuestion);
  const input: PreviewBoundaryInput | null = previewQuestion
    ? {
        questionType: previewQuestion.question_type,
        slotIndex: previewQuestion.slot_index,
        customDistance: previewQuestion.custom_distance ?? null,
      }
    : null;
  return usePreviewBoundaryFor(input);
}
