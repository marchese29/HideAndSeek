import { authHeader } from '@/api/auth';
import { api } from '@/api/client';

/** Answer a question as hider. Returns true on success. */
export async function answerQuestion(gameId: string, questionId: string): Promise<boolean> {
  const { error } = await api.POST('/games/{game_id}/questions/{question_id}/answer', {
    params: {
      path: { game_id: gameId, question_id: questionId },
      header: authHeader(),
    },
  });
  return !error;
}

/** Veto a question as hider. Returns true on success. */
export async function vetoQuestion(gameId: string, questionId: string): Promise<boolean> {
  const { error } = await api.POST('/games/{game_id}/questions/{question_id}/veto', {
    params: {
      path: { game_id: gameId, question_id: questionId },
      header: authHeader(),
    },
  });
  return !error;
}

/** Abandon a question as seeker. Returns true on success. */
export async function abandonQuestion(gameId: string, questionId: string): Promise<boolean> {
  const { error } = await api.POST('/games/{game_id}/questions/{question_id}/abandon', {
    params: {
      path: { game_id: gameId, question_id: questionId },
      header: authHeader(),
    },
  });
  return !error;
}

/** Lock in the seeker's end position for a thermometer question. Returns true on success. */
export async function lockInThermometer(gameId: string, questionId: string): Promise<boolean> {
  const { error } = await api.POST('/games/{game_id}/questions/thermometer/{question_id}/lock-in', {
    params: {
      path: { game_id: gameId, question_id: questionId },
      header: authHeader(),
    },
  });
  return !error;
}
