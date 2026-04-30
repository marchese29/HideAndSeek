import type { PauseReason } from '@/types/gameplay';

/**
 * True if any active reason mandates a universal modal (host pause, rest period).
 * When false, a reason-targeted banner renders instead.
 */
export function isUniversalCategory(reasons: PauseReason[]): boolean {
  return reasons.some((r) => r === 'host' || r === 'rest_period');
}
