import { useEffect, useState } from 'react';

import { parseUtc } from '@/utils/time';

/**
 * Formats milliseconds as HH:MM:SS. Always includes hours for consistent
 * display width (supports up to 99:59:59).
 */
function formatTime(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.min(99, Math.floor(totalSeconds / 3600));
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  const hh = String(hours).padStart(2, '0');
  const mm = String(minutes).padStart(2, '0');
  const ss = String(seconds).padStart(2, '0');

  return `${hh}:${mm}:${ss}`;
}

/**
 * Ticks every second and returns a formatted timer string.
 *
 * - Hiding phase: countdown to `hidingEndsAt` (server-authoritative future deadline,
 *   pause-shifted on resume), clamped to 00:00:00.
 * - Seeking phase: elapsed since `seekingStartedAt`, minus accumulated pause seconds,
 *   minus the in-flight pause window when currently paused.
 * - Other phases: returns "--:--:--".
 *
 * While paused, the tick is skipped — the displayed value is stable so re-renders
 * are unnecessary.
 */
export function useGameTimer(
  phase: string,
  hidingEndsAt: string | null,
  seekingStartedAt: string | null,
  seekingPauseAccumulatedSec: number,
  paused: boolean,
  pausedAt: string | null,
): string {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (paused) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [paused]);

  const referenceMs = paused && pausedAt ? parseUtc(pausedAt) : Date.now();

  if (phase === 'hiding' && hidingEndsAt) {
    const remaining = Math.max(0, parseUtc(hidingEndsAt) - referenceMs);
    return formatTime(remaining);
  }

  if (phase === 'seeking' && seekingStartedAt) {
    const elapsed = Math.max(
      0,
      referenceMs - parseUtc(seekingStartedAt) - seekingPauseAccumulatedSec * 1000,
    );
    return formatTime(elapsed);
  }

  return '--:--:--';
}
