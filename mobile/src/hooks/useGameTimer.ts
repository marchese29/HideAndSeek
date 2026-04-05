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
 * - Hiding phase: countdown from (hidingStartedAt + hidingTimeMin) to now, clamped to 00:00.
 * - Seeking phase: elapsed time since seekingStartedAt.
 * - Other phases: returns "--:--".
 */
export function useGameTimer(
  phase: string,
  hidingStartedAt: string | null,
  hidingTimeMin: number,
  seekingStartedAt: string | null,
): string {
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  if (phase === 'hiding' && hidingStartedAt) {
    const endMs = parseUtc(hidingStartedAt) + hidingTimeMin * 60_000;
    const remaining = Math.max(0, endMs - Date.now());
    return formatTime(remaining);
  }

  if (phase === 'seeking' && seekingStartedAt) {
    const elapsed = Math.max(0, Date.now() - parseUtc(seekingStartedAt));
    return formatTime(elapsed);
  }

  return '--:--:--';
}
