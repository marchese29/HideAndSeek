import { useQuery } from '@tanstack/react-query';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import { useAppStore } from '@/store';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { GeoJSONGeometry, SeekerActiveQuestion } from '@/types/gameplay';

/**
 * Fetches and caches the exclusion boundary for the currently active question.
 * Uses the seeker's ask-time location (seeker_location_start) so the boundary
 * stays fixed even as the seeker moves. Falls back to current selfLocation if
 * seeker_location_start is absent (SSE reconnection case).
 */
export function useActiveQuestionBoundary(): {
  boundary: GeoJSONGeometry | null;
  questionType: string | null;
} {
  const gameId = useAppStore((s) => s.gameId);
  const activeQuestion = useGameplayStore((s) =>
    s.status === 'connected' && s.role === 'seeker' ? s.state.active_question : null,
  ) as SeekerActiveQuestion | null;
  const selfLocation = useGameplayStore((s) => s.selfLocation);

  const questionId = activeQuestion?.question_id ?? null;
  const questionType = activeQuestion?.question_type ?? null;
  const slotIndex = activeQuestion?.slot_index ?? null;

  // Prefer ask-time location; fall back to current position after SSE reconnection
  const askLocation = activeQuestion?.seeker_location_start ?? selfLocation?.coordinates ?? null;
  const lat = askLocation ? askLocation.coordinates[1] : null;
  const lng = askLocation ? askLocation.coordinates[0] : null;

  const enabled =
    gameId !== null &&
    activeQuestion !== null &&
    questionType !== 'thermometer' &&
    lat !== null &&
    lng !== null;

  const { data } = useQuery({
    queryKey: ['active-boundary', gameId, questionId],
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
            lat: lat!,
            lng: lng!,
          },
          header: authHeader(),
        },
      });
      if (error) throw new Error('Active boundary fetch failed');
      return data;
    },
    enabled,
    gcTime: 300_000,
  });

  return {
    boundary: (data?.boundary as GeoJSONGeometry | undefined) ?? null,
    questionType,
  };
}
