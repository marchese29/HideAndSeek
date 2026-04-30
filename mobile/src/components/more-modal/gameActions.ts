import { router } from 'expo-router';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import { useAppStore } from '@/store';

/** Leave the game (optionally transferring host), clear session, navigate home. */
export async function doLeave(gameId: string, playerId: string, newHostId?: string): Promise<void> {
  try {
    await api.DELETE('/games/{game_id}/players/{player_id}', {
      params: {
        path: { game_id: gameId, player_id: playerId },
        header: authHeader(),
      },
      body: newHostId ? { new_host_id: newHostId } : null,
    });
  } catch {
    // Game may already be dissolved — still clear session
  }
  useAppStore.getState().clearSession();
  if (router.canDismiss()) router.dismissAll();
  router.replace('/');
}

/** End the game for all players. Returns true on success. */
export async function doEndGame(gameId: string): Promise<boolean> {
  try {
    await api.POST('/games/{game_id}/end', {
      params: {
        path: { game_id: gameId },
        header: authHeader(),
      },
    });
    return true;
  } catch {
    return false;
  }
}

/** Host-pause the game. Returns true on success. */
export async function doPause(gameId: string): Promise<boolean> {
  try {
    await api.POST('/games/{game_id}/pause', {
      params: {
        path: { game_id: gameId },
        header: authHeader(),
      },
    });
    return true;
  } catch {
    return false;
  }
}

/** Release the host pause. Returns true on success. */
export async function doResume(gameId: string): Promise<boolean> {
  try {
    await api.POST('/games/{game_id}/resume', {
      params: {
        path: { game_id: gameId },
        header: authHeader(),
      },
    });
    return true;
  } catch {
    return false;
  }
}

/** Kick a player from the game. Returns true on success. */
export async function doKick(gameId: string, targetPlayerId: string): Promise<boolean> {
  try {
    await api.DELETE('/games/{game_id}/players/{player_id}', {
      params: {
        path: { game_id: gameId, player_id: targetPlayerId },
        header: authHeader(),
      },
    });
    return true;
  } catch {
    return false;
  }
}
