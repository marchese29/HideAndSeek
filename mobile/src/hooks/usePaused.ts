import { useGameplayStore } from '@/stores/gameplayStore';
import type { PauseReason } from '@/types/gameplay';

const EMPTY_REASONS: PauseReason[] = [];

/**
 * Selector hook for pause state from the gameplay snapshot.
 * Consumers OR `paused` into their existing `disabled` expression.
 */
export function usePaused(): {
  paused: boolean;
  pausedAt: string | null;
  pauseReasons: PauseReason[];
} {
  const paused = useGameplayStore((s) =>
    s.status === 'connected' ? (s.state.paused ?? false) : false,
  );
  const pausedAt = useGameplayStore((s) =>
    s.status === 'connected' ? (s.state.paused_at ?? null) : null,
  );
  const pauseReasons = useGameplayStore((s) =>
    s.status === 'connected' ? (s.state.active_pause_reasons ?? EMPTY_REASONS) : EMPTY_REASONS,
  );
  return { paused, pausedAt, pauseReasons };
}
