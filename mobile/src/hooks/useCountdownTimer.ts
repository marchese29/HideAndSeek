import { useEffect, useState } from 'react';

import { parseUtc } from '@/utils/time';

interface PauseOpts {
  paused?: boolean;
  pausedAt?: string | null;
}

/**
 * Counts down to an ISO deadline, ticking every second.
 *
 * Returns remaining seconds (clamped to 0), or null if no deadline.
 *
 * When `paused` is true and `pausedAt` is set, remaining freezes at
 * `(deadline - pausedAt)` and the 1s tick is skipped — the value is stable.
 * Continuity at resume is automatic: the server shifts the deadline forward
 * by exactly `now - paused_at`, so `deadline - now` post-resume equals the
 * frozen `deadline - pausedAt` from before the resume.
 */
export function useCountdownTimer(
  deadlineIso: string | null,
  { paused = false, pausedAt = null }: PauseOpts = {},
): number | null {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!deadlineIso || paused) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [deadlineIso, paused]);

  if (!deadlineIso) return null;

  const referenceMs = paused && pausedAt ? parseUtc(pausedAt) : Date.now();
  const remaining = Math.max(0, Math.floor((parseUtc(deadlineIso) - referenceMs) / 1000));
  return remaining;
}
