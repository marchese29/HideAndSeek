import { authHeader } from '@/api/auth';
import { api, API_BASE_URL } from '@/api/client';

export type PhotoApiResult = { ok: true } | { ok: false; status: number; detail: string };

export interface PickedAsset {
  uri: string;
  name: string;
  type: string;
}

async function readDetail(resp: Response): Promise<string> {
  try {
    const json = (await resp.json()) as { detail?: unknown };
    return typeof json?.detail === 'string' ? json.detail : `HTTP ${resp.status}`;
  } catch {
    return `HTTP ${resp.status}`;
  }
}

function photoUrl(gameId: string, questionId: string): string {
  return `${API_BASE_URL}/games/${encodeURIComponent(gameId)}/questions/${encodeURIComponent(questionId)}/photo`;
}

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

/** Randomize a question as hider. Returns ok or an error detail for user display. */
export async function randomizeQuestion(
  gameId: string,
  questionId: string,
): Promise<{ ok: true } | { ok: false; detail: string }> {
  const { error } = await api.POST('/games/{game_id}/questions/{question_id}/randomize', {
    params: {
      path: { game_id: gameId, question_id: questionId },
      header: authHeader(),
    },
  });
  if (error) {
    const detail = (error as { detail?: string }).detail ?? 'Unable to randomize this question.';
    return { ok: false, detail };
  }
  return { ok: true };
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

/** Accept a submitted photo as seeker. Returns true on success. */
export async function acceptPhoto(gameId: string, questionId: string): Promise<boolean> {
  const { error } = await api.POST('/games/{game_id}/questions/{question_id}/accept', {
    params: {
      path: { game_id: gameId, question_id: questionId },
      header: authHeader(),
    },
  });
  return !error;
}

/** Reject a submitted photo as seeker. Returns true on success. */
export async function rejectPhoto(gameId: string, questionId: string): Promise<boolean> {
  const { error } = await api.POST('/games/{game_id}/questions/{question_id}/reject', {
    params: {
      path: { game_id: gameId, question_id: questionId },
      header: authHeader(),
    },
  });
  return !error;
}

/** Upload a photo for a photo question (queue or queue+submit). */
export async function uploadPhoto(
  gameId: string,
  questionId: string,
  asset: PickedAsset,
  options: { submit: boolean },
): Promise<PhotoApiResult> {
  const form = new FormData();
  // RN FormData typing for files differs from web — cast to satisfy TS.
  form.append('file', { uri: asset.uri, name: asset.name, type: asset.type } as unknown as Blob);
  form.append('submit', options.submit ? 'true' : 'false');
  const resp = await fetch(photoUrl(gameId, questionId), {
    method: 'POST',
    headers: authHeader(),
    body: form,
  });
  if (resp.ok) return { ok: true };
  return { ok: false, status: resp.status, detail: await readDetail(resp) };
}

/** Submit an already-queued photo without re-uploading bytes. */
export async function submitQueuedPhoto(
  gameId: string,
  questionId: string,
): Promise<PhotoApiResult> {
  const form = new FormData();
  form.append('submit', 'true');
  const resp = await fetch(photoUrl(gameId, questionId), {
    method: 'POST',
    headers: authHeader(),
    body: form,
  });
  if (resp.ok) return { ok: true };
  return { ok: false, status: resp.status, detail: await readDetail(resp) };
}

/** Submit a null answer for a photo question ("can't get this photo"). */
export async function submitNullPhoto(gameId: string, questionId: string): Promise<PhotoApiResult> {
  const resp = await fetch(photoUrl(gameId, questionId), {
    method: 'POST',
    headers: { ...authHeader(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ null: true }),
  });
  if (resp.ok) return { ok: true };
  return { ok: false, status: resp.status, detail: await readDetail(resp) };
}

/** Clear a queued photo without submitting. */
export async function unqueuePhoto(gameId: string, questionId: string): Promise<PhotoApiResult> {
  const resp = await fetch(photoUrl(gameId, questionId), {
    method: 'DELETE',
    headers: authHeader(),
  });
  if (resp.ok) return { ok: true };
  return { ok: false, status: resp.status, detail: await readDetail(resp) };
}
