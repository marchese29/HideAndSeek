/**
 * Validate a user-entered custom distance string. Mirrors server-side bounds:
 * positive, finite, under 100,000 (km or mi depending on game convention),
 * and short enough to render cleanly in compact UI.
 */
export function validateCustomDistance(text: string): boolean {
  if (!text) return false;
  const num = Number(text);
  return !isNaN(num) && num > 0 && num < 100000 && text.length <= 8;
}
