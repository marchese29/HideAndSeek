import { useQuery } from '@tanstack/react-query';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import { useAppStore } from '@/store';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { GeoJSONGeometry, HiderActiveQuestion } from '@/types/gameplay';

/**
 * Fetches and caches the exclusion boundary for the active question as seen by
 * a hider. Uses the seeker's ask-time location (from QuestionAskedEvent) and,
 * for thermometer questions, the lock-in end location (from
 * QuestionAnswerableEvent).
 *
 * Only enabled when the question is answerable and required parameters are
 * present (absent after SSE reconnection — boundary simply won't render).
 */
export function useHiderQuestionBoundary(): {
  boundary: GeoJSONGeometry | null;
  questionType: string | null;
} {
  const gameId = useAppStore((s) => s.gameId);
  const activeQuestion = useGameplayStore((s) =>
    s.status === 'connected' && s.role === 'hider' ? s.state.active_question : null,
  ) as HiderActiveQuestion | null;

  const questionId = activeQuestion?.question_id ?? null;
  const questionType = activeQuestion?.question_type ?? null;
  const slotIndex = activeQuestion?.slot_index ?? null;
  const status = activeQuestion?.status ?? null;
  const seekerStart = activeQuestion?.seeker_location_start ?? null;
  const seekerEnd = activeQuestion?.seeker_location_end ?? null;

  const lat = seekerStart ? seekerStart.coordinates[1] : null;
  const lng = seekerStart ? seekerStart.coordinates[0] : null;

  // Thermometer needs end location; other types just need start
  const isThermometer = questionType === 'thermometer';
  const endLat = seekerEnd ? seekerEnd.coordinates[1] : undefined;
  const endLng = seekerEnd ? seekerEnd.coordinates[0] : undefined;

  const enabled =
    gameId !== null &&
    activeQuestion !== null &&
    status === 'answerable' &&
    lat !== null &&
    lng !== null &&
    (!isThermometer || (endLat !== undefined && endLng !== undefined));

  const { data } = useQuery({
    queryKey: ['hider-boundary', gameId, questionId],
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
            ...(isThermometer ? { end_lat: endLat!, end_lng: endLng! } : {}),
          },
          header: authHeader(),
        },
      });
      if (error) throw new Error('Hider boundary fetch failed');
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
