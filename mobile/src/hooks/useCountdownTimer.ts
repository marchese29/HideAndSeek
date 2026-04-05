import { useEffect, useState } from 'react';

import { parseUtc } from '@/utils/time';

/**
 * Counts down to an ISO deadline, ticking every second.
 *
 * Returns remaining seconds (clamped to 0), or null if no deadline.
 */
export function useCountdownTimer(deadlineIso: string | null): number | null {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!deadlineIso) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [deadlineIso]);

  if (!deadlineIso) return null;

  const remaining = Math.max(0, Math.floor((parseUtc(deadlineIso) - Date.now()) / 1000));
  return remaining;
}
