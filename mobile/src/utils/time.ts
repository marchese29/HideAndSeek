/**
 * Parse a server timestamp as UTC. The server may send timestamps in
 * three forms:
 * - Naive (no suffix): Pydantic serializes DB timestamps without 'Z'
 * - 'Z' suffix: explicit UTC
 * - '+00:00' suffix: tz-aware UTC (e.g., computed datetimes that haven't
 *   round-tripped through the DB)
 *
 * JavaScript's Date() treats naive strings as local time, so we append
 * 'Z' only when no timezone info is present.
 */
export function parseUtc(iso: string): number {
  // Already has timezone info (Z or ±HH:MM offset after the time portion)
  if (/Z|[+-]\d{2}:\d{2}$/.test(iso)) {
    return new Date(iso).getTime();
  }
  // Naive timestamp — treat as UTC
  return new Date(iso + 'Z').getTime();
}
